"""Rule-based parser for standard pilot phraseology. Deterministic and fast; the LLM is only a fallback."""
import difflib
import re

from atc.intent.normalize import PHONETIC, tokenize
from atc.intent.schema import Intent
from atc.phraseology.airlines import TELEPHONY
from atc.units import parse_mhz

TELEPHONY_TO_CODE = {name.lower(): code for code, name in TELEPHONY.items()}
CALLSIGN_MATCH_RATIO = 0.6  # we are the only pilot, so this only has to reject "no callsign at all" and garbage
FUZZY_TELEPHONY_CUTOFF = 0.7  # "Luftanzar", "Lufthansaw", "Luftonza" -> Lufthansa
# Pilots don't always say "request": "we would like to get our clearance", "can we have pushback"
REQUEST = re.compile(r"\brequest(?:ing)?\b|\bwould like\b|\b(?:can|could|may) (?:we|i) (?:get|have)\b"
                     r"|\blike to (?:get|have)\b")
# Readbacks of instructions without values: "push and start approved, facing east", "continue taxi"
INSTRUCTION_ACK = re.compile(r"\bapproved\b|\bcontinu(?:e|ing)\b|\bpushing back\b|\bfacing (?:north|east|south|west)\b"
                             r"|\bident\b|\bin sight\b|\blooking (?:out)?\b|\bno contact\b"
                             r"|\bhold(?:ing)? position\b"  # "hold position, traffic passing behind"
                             r"|\bgiv(?:e|ing) way\b|\bfollow(?:ing)?\b")  # "give way to / follow the Airbus"
ACKNOWLEDGE = re.compile(r"\b(roger|wilco|affirm|affirmative|negative|copied|standby|stand by"
                         r"|stopping(?: immediately)?)\b")  # "Lufthansa 758 stopping immediately" (B5)


def parse(text: str, expected_callsign: str | None = None) -> Intent:
    tokens = tokenize(text)
    callsign, span = find_callsign(tokens, expected_callsign)
    if callsign is None and expected_callsign:  # "it turns out, two for one": the airline misheard, the number not
        callsign, span = flight_number_only(tokens, expected_callsign)
    rest = [PHONETIC.get(tok, tok) for i, tok in enumerate(tokens) if i not in span]
    joined = " ".join(rest)
    items = extract_items(rest, joined)
    return Intent(
        kind=classify(joined, items),
        callsign=callsign,
        addressed_to_us=bool(callsign and expected_callsign and callsign_matches(callsign, expected_callsign)),
        items=items,
        text=" ".join(tokens),
    )


def flight_number_only(tokens: list[str], expected: str) -> tuple[str | None, set[int]]:
    """Our callsign when the airline name was misheard but the flight number is there in full, e.g. "two for one" for
    Lufthansa 241. We are the only pilot, so the number alone is enough. ("for" between digits is "four".)"""
    m = re.fullmatch(r"[A-Z]{3}(\d[A-Z0-9]*)", expected.upper())
    if not m:
        return None, set()
    wanted = m[1].lower()
    for i in range(len(tokens)):
        built, j = "", i
        while j < len(tokens) and len(built) < len(wanted):
            tok = tokens[j]
            if tok == "for" and built and built[-1].isdigit():
                tok = "4"
            tok = PHONETIC.get(tok, tok)
            if not (tok.isdigit() or len(tok) == 1):
                break
            built += tok
            j += 1
        if built == wanted:
            return expected.upper(), set(range(i, j))
    return None, set()


def callsign_matches(heard: str, expected: str) -> bool:
    return difflib.SequenceMatcher(None, heard.upper(), expected.upper()).ratio() >= CALLSIGN_MATCH_RATIO


def find_callsign(tokens: list[str], expected: str | None = None) -> tuple[str | None, set[int]]:
    """Returns (callsign, token indices it used). With several candidates (a taxiway "delta 1" looks like the
    airline Delta), the one most similar to the expected callsign wins, otherwise the first."""
    candidates: list[tuple[str, set[int]]] = []
    own = expected[:3].upper() if expected and expected[:3].upper() in TELEPHONY else None
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        after = tokens[i + 2] if i + 2 < len(tokens) else ""
        code, start, first = None, i + 1, ""
        if (two := TELEPHONY_TO_CODE.get(f"{tok} {nxt}")) and _starts_flight_number(after):  # "air canada 123"
            code, start = two, i + 2
        elif (airline := _telephony_code(tok, own, expected is not None)) and _starts_flight_number(nxt):
            code = airline
        elif m := re.fullmatch(r"([a-z]{3})(\d[a-z0-9]*)", tok):  # "dlh4ab", "glh4ab"
            code, first = m[1].upper(), m[2].upper()
        elif re.fullmatch(r"[a-z]{3}", tok) and tok.upper() in TELEPHONY and _starts_flight_number(nxt):  # "dlh 4ab"
            code = tok.upper()
        if code:
            # Stop at our own callsign: whisper, primed with "Lufthansa 4AB", sometimes writes "4AB, Bravo"
            done = expected.upper()[len(code + first):] if expected and expected.upper().startswith(code + first) else None
            rest, end = _collect_flight_id(tokens, start, done)
            if first or rest:
                candidates.append((code + first + rest, set(range(i, end))))
    if not candidates:
        return None, set()
    if expected:
        return max(candidates, key=lambda c: difflib.SequenceMatcher(None, c[0], expected.upper()).ratio())
    return candidates[0]


def _telephony_code(tok: str, own: str | None = None, expecting: bool = False) -> str | None:
    """The airline code for a telephony word, also misheard ("luftanzar"). With an expected callsign, a misheard
    word only counts as our own airline: the pilot says no other, and with 140 airlines some word of an
    instruction would otherwise look like one."""
    if tok in TELEPHONY_TO_CODE:
        return TELEPHONY_TO_CODE[tok]
    if len(tok) >= 5 and tok not in PHONETIC:
        # Similar length too: otherwise "speed" (as in "speed 180") would match "Speedbird"
        names = ([TELEPHONY[own].lower()] if own else []) if expecting else list(TELEPHONY_TO_CODE)
        names = [n for n in names if abs(len(n) - len(tok)) <= 2]
        close = difflib.get_close_matches(tok, names, n=1, cutoff=FUZZY_TELEPHONY_CUTOFF)
        if close:
            return TELEPHONY_TO_CODE[close[0]]
    return None


def _starts_flight_number(tok: str) -> bool:
    return tok == "for" or bool(re.fullmatch(r"[a-z]?\d[a-z0-9]*", tok))


def _collect_flight_id(tokens: list[str], j: int, done: str | None = None) -> tuple[str, int]:
    """Digits, letters and phonetic words after the airline, e.g. '4 alpha bravo' -> '4AB'. Stops once the parts
    are `done` (the rest of our callsign)."""
    parts = ""
    while j < len(tokens) and len(parts) < 6 and (done is None or parts != done):
        tok = tokens[j]
        nxt = tokens[j + 1] if j + 1 < len(tokens) else ""
        if tok.isdigit():
            parts += tok
        elif tok == "for" and (nxt in PHONETIC or nxt.isdigit() or len(nxt) == 1):
            parts += "4"  # "Lufthansa for Alpha Bravo": whisper hears "four" as "for"
        elif tok in PHONETIC:
            parts += PHONETIC[tok].upper()
        elif re.fullmatch(r"[a-z]", tok) or re.fullmatch(r"[a-z]?\d[a-z0-9]{0,4}", tok):
            parts += tok.upper()
        else:
            break
        j += 1
    return parts, j


def extract_items(tokens: list[str], t: str) -> dict:
    items: dict = {}
    if m := re.search(r"\b(?:flight level|fl) (\d) hundred\b", t):
        items["flight_level"] = int(m[1]) * 100
    elif m := re.search(r"\b(?:flight level|level|fl) (\d{2,3})\b", t):
        items["flight_level"] = int(m[1])

    if m := re.search(r"\b(\d{1,2}) thousand(?: (\d) hundred)?\b", t):
        items["altitude_ft"] = int(m[1]) * 1000 + (int(m[2]) * 100 if m[2] else 0)
    elif m := (re.search(r"\b(\d{3,5}) (?:feet|ft)\b", t) or re.search(r"\baltitude (\d{3,5})\b", t)
               or re.search(r"\b(?:climb|descend|maintain)(?:ing)? (?:to )?(\d{3,5})\b", t)):
        items["altitude_ft"] = int(m[1])
    elif m := re.search(r"\b(\d) hundred (?:feet|ft)\b", t):
        items["altitude_ft"] = int(m[1]) * 100

    if (m := re.search(r"\bheading (\d{1,3})\b", t)) and 1 <= int(m[1]) <= 360:
        items["heading"] = int(m[1])
    if m := re.search(r"\bspeed (\d{2,3})\b", t):
        items["speed_kt"] = int(m[1])
    if m := re.search(r"\bsquawk(?:ing)? (\d{4})\b", t):
        items["squawk"] = m[1]
    if m := re.search(r"\bqnh (\d{3,4})\b", t):
        items["qnh"] = int(m[1])
    if m := re.search(r"\binformation ([a-z])\b", t):
        items["atis"] = m[1]

    for tok in tokens:
        if re.fullmatch(r"\d{3}\.\d{1,3}", tok):
            try:
                items["frequency_khz"] = parse_mhz(tok)
                break
            except ValueError:
                continue

    for m in re.finditer(r"\b(short (?:of )?)?runway (\d{1,2})([lrc])?(?: (left|right|center|centre))?\b", t):
        side = m[3] or (m[4][0] if m[4] else "")  # "08r" as whisper writes it, or "08 right"
        name = f"{int(m[2]):02}" + side.upper()
        if m[1]:
            items["hold_short"] = name
        else:
            items.setdefault("runway", name)
    # "holding short zero five": pilots often leave out the word "runway"
    if "hold_short" not in items and (
            m := re.search(r"\bshort (?:of )?(\d{1,2})([lrc])?(?: (left|right|center|centre))?\b", t)):
        items["hold_short"] = f"{int(m[1]):02}" + (m[2] or (m[3][0] if m[3] else "")).upper()

    if taxiways := _taxiways(tokens):
        items["taxiways"] = taxiways
    if re.search(r"\bcleared (?:for )?takeoff\b", t):
        items["cleared_takeoff"] = True
    if re.search(r"\bcleared (?:to )?land\b", t):
        items["cleared_land"] = True
    if re.search(r"\bpush(?:back| back)?(?: and start(?:up)?)? approved\b|\bpushing back\b"
                 r"|\bstart(?:up)? approved\b", t):  # "Potion start approved"
        items["pushback"] = True
    if re.search(r"\bline up and wait\b|\blining up\b", t):
        items["line_up"] = True
    if re.search(r"\bhold(?:ing)? position\b", t):
        items["hold_position"] = True
    if re.search(r"\bprogressive\b", t):  # "request progressive taxi"
        items["progressive"] = True
    if m := re.search(r"\b(?:direct|dct) (?:to )?([a-z]{2,5})\b", t):
        items["direct"] = m[1].upper()
    # "from intersection bravo 4", "intersection departure b4", "from b4"
    if m := re.search(r"\b(?:intersection|from) (?:departure )?([a-z]) ?(\d{1,2})\b", t):
        items["intersection"] = f"{m[1].upper()}{m[2]}"
    return items


def _taxiways(tokens: list[str]) -> list[str]:
    """'via a 1 b' -> ['A1', 'B']. A letter after a number starts the next taxiway, so 'Z5B' reads as Z5, B."""
    if "via" not in tokens:
        return []
    names: list[str] = []
    i = tokens.index("via") + 1
    while i < len(tokens):
        tok = tokens[i]
        if re.fullmatch(r"[a-z]", tok):
            name = tok.upper()
            if i + 1 < len(tokens) and re.fullmatch(r"\d{1,2}", tokens[i + 1]):
                name += tokens[i + 1]
                i += 1
            names.append(name)
        elif re.fullmatch(r"[a-z]\d{1,2}", tok):
            names.append(tok.upper())
        elif tok != "and":
            break
        i += 1
    return names


def classify(t: str, items: dict) -> str:
    if re.search(r"\bgo(?:ing)? around\b|\bmissed approach\b", t):
        return "going_around"
    if "radio check" in t:
        return "radio_check"
    if re.search(r"\bsay again\b", t):
        return "say_again"
    if re.search(r"\bunable\b", t):  # can't comply, also "unable heading 190"
        return "unable"
    if re.match(r"(?:\w+ ){0,3}confirm\b", t):  # "confirm cleared ILS runway 08R?"
        return "confirm"
    if re.search(r"\b(?:say|request|what is the) (?:the )?(?:qnh|altimeter)\b", t):
        return "request_qnh"
    if re.search(r"\bready to copy\b", t):  # ready to receive the clearance
        return "request_clearance"
    # At a runway crossing (or the departure runway): "holding short runway 05", "ready to cross runway 05",
    # "request crossing runway 05". A readback of "cross runway 05" ("crossing runway 05") is not one, and a
    # readback of a taxi clearance that ends in "holding short runway 05" has taxiways in it.
    if (re.search(r"\bholding short\b|\bready to cross\b|\brequest(?:ing)? (?:to )?cross(?:ing)?\b", t)
            and "taxiways" not in items):
        return "holding_short"
    # "on holding point (runway 33)" (Milestone 8, C1; STT heard "one holding point"), but not the readback
    # "taxi to holding point runway 33"
    if (re.search(r"\b(?:on|at|one|1|in|reaching) (?:the )?holding point\b", t) and not re.search(r"\btaxi\b", t)
            and "taxiways" not in items and not re.search(r"\bready\b", t)):
        return "holding_short"
    if re.search(r"\bwind check\b", t):
        return "request_wind"
    if REQUEST.search(t):
        if re.search(r"\bline ?up\b", t):
            return "request_line_up"
        if re.search(r"\bpush(?:back)?\b|\bpush back\b|\bstart ?up\b|\bstart(?:ing)? (?:the )?engines?\b"
                     r"|\bengine start\b", t):
            return "request_pushback"
        if re.search(r"\bweather\b|\bmetar\b", t):
            return "request_weather"
        if re.search(r"\bclearance\b|\bifr\b", t):
            return "request_clearance"
        if re.search(r"\btaxi\b", t):
            return "request_taxi"
        if re.search(r"\bdescent\b|\blower\b", t):
            return "request_descent"
        if "direct" in items:
            return "request_direct"
        if re.search(r"\bhigher\b|\bclimb\b", t) or "flight_level" in items:
            return "request_level"
        return "request_other"
    if re.search(r"\bready (?:for )?(?:departure|takeoff)\b", t):
        return "ready_departure"
    if re.search(r"\bready (?:for|to) taxi\b", t):
        return "request_taxi"
    if re.search(r"\bready\b.*\bholding point\b|\bholding point\b.*\bready\b", t):  # "ready at holding point 23"
        return "ready_departure"
    if re.search(r"\bvacated\b", t):
        return "vacated"
    if re.search(r"\bwith you\b|\bpassing\b|\bestablished\b|\bpush ?(?:back )?(?:is )?completed?\b", t):
        return "checkin"
    # A first call with nothing else in it, "Hamburg Ground, Lufthansa 4AB": ATC answers "go ahead"
    if re.fullmatch(r"(?:[a-z]+ ){0,2}(?:ground|tower|approach|radar|delivery|apron|departure|center|centre|control)"
                    r"(?: (?!stand ?by\b)[a-z0-9]+)?", t):  # but "Hamburg Ground, …, standby" means wait
        return "checkin"
    if items:
        return "readback"
    if ACKNOWLEDGE.search(t) or INSTRUCTION_ACK.search(t):
        return "acknowledge"
    return "unknown"
