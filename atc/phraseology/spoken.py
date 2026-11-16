"""Turns values into ICAO radiotelephony words (Annex 10 Vol II, 5.2.1.4). Output is plain text for TTS."""
import re

from atc.phraseology.airlines import TELEPHONY

DIGITS = {
    "0": "zero", "1": "one", "2": "two", "3": "tree", "4": "four",
    "5": "fife", "6": "six", "7": "seven", "8": "eight", "9": "niner",
}
ALPHABET = {
    "A": "Alfa", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo", "F": "Foxtrot", "G": "Golf",
    "H": "Hotel", "I": "India", "J": "Juliett", "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November",
    "O": "Oscar", "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango", "U": "Uniform",
    "V": "Victor", "W": "Whiskey", "X": "X-ray", "Y": "Yankee", "Z": "Zulu",
}
RUNWAY_SIDE = {"L": "left", "R": "right", "C": "center"}


def digits(value: int | str) -> str:
    text = str(value)
    if not text.isdigit():
        raise ValueError(f"not a digit string: {value!r}")
    return " ".join(DIGITS[c] for c in text)


def spell(text: str) -> str:
    """Spell letters and digits one by one: 'D-EABC' -> 'Delta Echo Alfa Bravo Charlie'."""
    chars = [c for c in text.upper() if c not in "- "]
    if not all(c in DIGITS or c in ALPHABET for c in chars):
        raise ValueError(f"cannot spell {text!r}")
    return " ".join(DIGITS.get(c) or ALPHABET[c] for c in chars)


def callsign(text: str) -> str:
    """'DLH4AB' -> 'Lufthansa four Alfa Bravo'. Unknown airlines and registrations are spelled out."""
    cs = text.upper().replace("-", "").replace(" ", "")
    m = re.fullmatch(r"([A-Z]{3})(\d[A-Z0-9]*)", cs)
    if m and m.group(1) in TELEPHONY:
        return f"{TELEPHONY[m.group(1)]} {spell(m.group(2))}"
    return spell(cs)


def registration(text: str) -> str | None:
    """'D-MABC' -> 'DMABC': a callsign that is an aircraft's registration (letters only, no airline and flight
    number), or None."""
    cs = text.upper().replace("-", "").replace(" ", "")
    return cs if re.fullmatch(r"[A-Z]{4,}", cs) else None


def short_callsign(text: str) -> str | None:
    """ICAO abbreviation of a registration: its first character and the last two, 'D-MABC' -> 'Delta Bravo
    Charlie'. Only after the controller used it first (atc/controller/controller.py). None for airlines."""
    reg = registration(text)
    return spell(reg[0] + reg[-2:]) if reg else None


def flight_level(feet: int) -> str:
    """12000 -> 'flight level one two zero'; whole hundreds are said as such: 10000 -> 'flight level one hundred'."""
    if feet % 100:
        raise ValueError(f"flight levels are whole hundreds of feet: {feet}")
    fl = feet // 100
    if fl % 100 == 0:
        return f"flight level {DIGITS[str(fl // 100)]} hundred"
    return f"flight level {digits(fl)}"


def altitude(feet: int) -> str:
    """3500 -> 'tree thousand fife hundred feet', 10000 -> 'one zero thousand feet'."""
    return f"{thousands_hundreds(feet)} feet"


def thousands_hundreds(value: int) -> str:
    """ICAO style for altitudes, cloud heights and visibility: 3500 -> 'tree thousand fife hundred'."""
    if value <= 0 or value % 100:
        raise ValueError(f"must be positive whole hundreds: {value}")
    thousands, hundreds = divmod(value, 1000)
    parts = []
    if thousands:
        parts.append(f"{digits(thousands)} thousand")
    if hundreds:
        parts.append(f"{DIGITS[str(hundreds // 100)]} hundred")
    return " ".join(parts)


def heading(degrees: float) -> str:
    """Always three digits, north is 360: 5 -> 'zero zero fife'."""
    h = round(degrees) % 360 or 360
    return digits(f"{h:03}")


def speed(knots: int) -> str:
    return f"{digits(knots)} knot" + ("" if knots == 1 else "s")  # "wind 010 degrees one knot"


def squawk(code: str) -> str:
    if not re.fullmatch(r"[0-7]{4}", code):
        raise ValueError(f"squawk codes are four octal digits: {code!r}")
    return digits(code)


def qnh(hpa: int) -> str:
    return digits(hpa)


def frequency(khz: int) -> str:
    """All six digits, except when the last two are zero: 121.280 -> '... two eight zero', 121.500 -> '... fife'."""
    mhz, rest = divmod(khz, 1000)
    decimals = str(rest // 100) if rest % 100 == 0 else f"{rest:03}"
    return f"{digits(mhz)} decimal {digits(decimals)}"


def runway(name: str) -> str:
    """'08L' -> 'zero eight left'."""
    m = re.fullmatch(r"(\d{2})([LRC]?)", name.upper())
    if not m:
        raise ValueError(f"not a runway designator: {name!r}")
    side = RUNWAY_SIDE.get(m.group(2))
    return digits(m.group(1)) + (f" {side}" if side else "")


def wind(direction: float | None, knots: int, gust_knots: int | None = None) -> str:
    """direction None means variable. 0 kt is calm."""
    if knots == 0:
        return "wind calm"
    where = "variable" if direction is None else f"{heading(direction)} degrees"
    text = f"wind {where} {speed(knots)}"
    if gust_knots:
        text += f" gusting {speed(gust_knots)}"
    return text
