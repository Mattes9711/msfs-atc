"""Spike (step 24, parked): LLM fallback for transmissions the rule parser doesn't understand.

Run from the project root, with Ollama running:  python -m spikes.s24_llm_fallback [model]

Result on 2026-11-14 with llama3.2 (3.2B, Q4) next to a running MSFS on an 8 GB RTX 3060 Ti:
- loading took 76 s, the model holds 2.1 GB VRAM next to MSFS's ~7.4 GB, 1.4-3.2 s per call (plus whisper's ~3 s)
- 3 of 6 free-form transmissions useful ("would like to get our IFR clearance" -> request_clearance,
  "ready whenever you are at holding point two three" -> ready_departure)
- invented values were caught by the checks below: squawk 0421 copied from the prompt's example ("not said"),
  "Golf One" as a runway; a heading/altitude readback came back without its values
Decision: no LLM for now. The rule parser learned the phrasings found here instead (step 24 in PLAN.md).
The schema/value/grounding checks are the part worth keeping if an LLM comes back (later version, local or cloud).

Original design notes: LLM fallback for transmissions the rule parser doesn't understand (step 24).

The LLM only turns words into an Intent. Everything it returns is checked deterministically before use:
- schema: a known kind, known items, the right types
- values: the runway exists, squawk is octal, the frequency is a COM channel, levels/headings/QNH in range
- grounding: every number must appear in what the pilot said, so the LLM can't invent a squawk or a level
- callsign: the rule parser's callsign wins; otherwise the LLM's is matched against ours like any other
Anything that fails is dropped (ATC then says "say again") and the reason is shown on screen.
"""
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol

from atc.intent.normalize import tokenize
from atc.intent.parser import callsign_matches
from atc.intent.schema import ITEMS, KINDS, Intent
from atc.units import COM_MAX_KHZ, COM_MIN_KHZ

KIND_HELP = {
    "request_clearance": "asks for the IFR clearance",
    "request_pushback": "asks for pushback and/or engine start",
    "request_taxi": "asks for taxi (or says ready to taxi)",
    "request_descent": "asks to descend",
    "request_other": "asks for something else",
    "ready_departure": "reports ready for departure / takeoff",
    "going_around": "reports going around / missed approach",
    "vacated": "reports the runway vacated",
    "checkin": "first call on a new frequency, position or level report, established on the approach",
    "readback": "repeats an ATC instruction back",
    "acknowledge": "roger / wilco / affirm / negative without values",
    "radio_check": "asks for a radio check",
    "say_again": "asks ATC to repeat",
    "unknown": "none of these, or not understandable",
}
# What the LLM may return. Frequencies come as MHz (as spoken) and are converted.
LLM_ITEMS = {k: t for k, t in ITEMS.items() if k != "frequency_khz"} | {"frequency_mhz": float}
JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array"}
NUMERIC_ITEMS = ("flight_level", "altitude_ft", "heading", "speed_kt", "squawk", "frequency_khz", "qnh")


class LlmUnavailable(Exception):
    pass


class IntentLLM(Protocol):
    """A backend: system + user message in, JSON text out (constrained to `schema` if it can)."""

    name: str

    def complete(self, system: str, user: str, schema: dict) -> str: ...


@dataclass(frozen=True)
class LlmContext:
    callsign: str  # "DLH4AB"
    spoken_callsign: str  # "Lufthansa four Alfa Bravo"
    station: str  # who the pilot is calling, e.g. "Hamburg Ground"
    phase: str
    runways: tuple[str, ...]  # runway ends that exist where we are
    last_atc: str | None = None  # what this station last said to us
    readback_expected: tuple[str, ...] = ()  # item names still to be read back


def output_schema() -> dict:
    items = {}
    for key, typ in LLM_ITEMS.items():
        prop = {"type": [JSON_TYPES[typ], "null"]}
        if typ is list:
            prop["items"] = {"type": "string"}
        items[key] = prop
    return {"type": "object", "required": ["kind", "callsign", "items"], "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "callsign": {"type": ["string", "null"]},
        "items": {"type": "object", "properties": items},
    }}


def system_prompt(ctx: LlmContext) -> str:
    kinds = "\n".join(f"- {k}: {v}" for k, v in KIND_HELP.items())
    expected = (f"\nThe pilot still has to read back: {', '.join(ctx.readback_expected)}."
                if ctx.readback_expected else "\nNothing is waiting to be read back.")
    last = f'\n{ctx.station} last said: "{ctx.last_atc}"' if ctx.last_atc else ""
    return f"""You turn ONE pilot radio transmission into JSON for an air traffic control program.
The text comes from speech recognition and may contain recognition errors ("for" instead of "four", "Hammer"
instead of "Hamburg"). You do not decide anything and you never add a value the pilot did not say: an item
that was not said is null. Numbers are given as said (flight level 350 -> 350, five thousand feet -> 5000,
squawk "zero four two one" -> "0421", one one eight decimal two zero five -> 118.205, information bravo -> "b").

kind is exactly one of:
{kinds}

callsign: the aircraft callsign as ICAO code + flight id without spaces (Lufthansa four alpha bravo -> DLH4AB),
or null if no callsign was said.

Situation: our aircraft is {ctx.callsign} ("{ctx.spoken_callsign}"), calling {ctx.station}, flight phase
{ctx.phase}. Runways here: {', '.join(ctx.runways) or 'unknown'}.{expected}{last}
Answer with the JSON object only."""


def digit_stream(text: str) -> str:
    return "".join(re.findall(r"\d", " ".join(tokenize(text))))


def validate(raw: str, heard: str, ctx: LlmContext, rule_callsign: str | None) -> Intent:
    """The LLM's answer as an Intent, or ValueError saying why it can't be used."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("not JSON") from None
    if not isinstance(data, dict) or data.get("kind") not in KINDS:
        raise ValueError(f"unknown kind {data.get('kind') if isinstance(data, dict) else data!r}")
    raw_items = data.get("items") or {}
    if not isinstance(raw_items, dict):
        raise ValueError("items is not an object")
    items = {}
    for key, value in raw_items.items():
        if value is None or value is False or value == [] or value == "":
            continue  # not said
        if key not in LLM_ITEMS:
            raise ValueError(f"unknown item {key}")
        items[key] = _typed(key, value)
    if "frequency_mhz" in items:
        items["frequency_khz"] = round(items.pop("frequency_mhz") * 1000)
    _check_values(items, ctx)
    _check_grounding(items, heard)

    if rule_callsign:
        callsign = rule_callsign
    else:
        heard_cs = data.get("callsign")
        callsign = re.sub(r"[^A-Z0-9]", "", heard_cs.upper()) if isinstance(heard_cs, str) else None
        if callsign and not _callsign_said(callsign, heard):
            callsign = None  # the LLM copied our callsign from the prompt
    return Intent(kind=data["kind"], callsign=callsign or None,
                  addressed_to_us=bool(callsign and callsign_matches(callsign, ctx.callsign)),
                  items=items, text=" ".join(tokenize(heard)))


def _typed(key: str, value):
    typ = LLM_ITEMS[key]
    if typ is int and isinstance(value, float) and value.is_integer():
        value = int(value)
    if typ is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if typ is int and isinstance(value, bool) or not isinstance(value, typ):
        raise ValueError(f"{key} has the wrong type: {value!r}")
    if typ is list:
        if not all(isinstance(v, str) for v in value):
            raise ValueError(f"{key} must be a list of names")
        value = [v.upper().replace(" ", "") for v in value]
    if typ is str:
        value = value.strip()
        if key in ("runway", "hold_short"):
            m = re.fullmatch(r"0?(\d{1,2})\s*([LRC]?)", value.upper())
            if not m:
                raise ValueError(f"runway {value!r}")
            value = f"{int(m[1]):02d}{m[2]}"  # "8L", "08l", "8 L" -> "08L"
        elif key == "atis":
            value = value.lower()
    return value


def _check_values(items: dict, ctx: LlmContext) -> None:
    def bad(why):
        raise ValueError(why)

    for key in ("runway", "hold_short"):
        if key in items and items[key] not in ctx.runways:
            bad(f"runway {items[key]} doesn't exist here")
    if "squawk" in items and not re.fullmatch(r"[0-7]{4}", items["squawk"]):
        bad(f"squawk {items['squawk']} is not four octal digits")
    if "frequency_khz" in items:
        khz = items["frequency_khz"]
        if not COM_MIN_KHZ <= khz <= COM_MAX_KHZ or khz % 5:
            bad(f"{khz / 1000:.3f} is not a COM frequency")
    ranges = {"flight_level": (10, 660), "altitude_ft": (100, 60000), "heading": (1, 360), "speed_kt": (60, 450),
              "qnh": (900, 1100)}
    for key, (low, high) in ranges.items():
        if key in items and not low <= items[key] <= high:
            bad(f"{key} {items[key]} is out of range")
    if "atis" in items and not re.fullmatch(r"[a-z]", items["atis"]):
        bad(f"ATIS letter {items['atis']!r}")
    for name in items.get("taxiways", []):
        if not re.fullmatch(r"[A-Z]{1,2}\d{0,2}", name):
            bad(f"taxiway {name!r}")


def _check_grounding(items: dict, heard: str) -> None:
    digits = digit_stream(heard)
    for key in NUMERIC_ITEMS:
        if key in items:
            value = str(items[key])
            if key == "frequency_khz":
                value = value.rstrip("0") or value  # 118.200 is often said "one one eight decimal two"
            if value not in digits:
                raise ValueError(f"{key} {items[key]} was not said")
    for key in ("runway", "hold_short"):
        if key in items and items[key].rstrip("LRC").lstrip("0") not in digits:
            raise ValueError(f"runway {items[key]} was not said")


def _callsign_said(callsign: str, heard: str) -> bool:
    """At least the flight number's digits must be in the transmission."""
    flight_digits = re.sub(r"\D", "", callsign[3:])
    return bool(flight_digits) and flight_digits in digit_stream(heard)


class LlmIntentParser:
    def __init__(self, backend: IntentLLM, clock: Callable[[], float] = time.perf_counter):
        self.backend, self.clock = backend, clock

    def parse(self, heard: str, ctx: LlmContext, rule_callsign: str | None = None) -> tuple[Intent | None, str]:
        """(intent or None, a line for the screen)."""
        start = self.clock()
        try:
            raw = self.backend.complete(system_prompt(ctx), heard, output_schema())
        except LlmUnavailable as e:
            return None, f"LLM fallback failed: {e}"
        took = self.clock() - start
        try:
            intent = validate(raw, heard, ctx, rule_callsign)
        except ValueError as e:
            return None, f"LLM answer rejected ({took:.1f} s): {e}"
        items = " ".join(f"{k}={v}" for k, v in intent.items.items())
        return intent, f"LLM ({self.backend.name}, {took:.1f} s): {intent.kind}" + (f", {items}" if items else "")


class OllamaBackend:
    """Local model through Ollama's HTTP API, with the answer constrained to the JSON schema."""

    def __init__(self, model: str = "llama3.2", url: str = "http://localhost:11434", timeout: float = 15,
                 post: Callable[[str, dict, float], dict] | None = None):
        self.model, self.url, self.timeout = model, url.rstrip("/"), timeout
        self.post = post or _post_json
        self.name = f"Ollama {model}"

    def complete(self, system: str, user: str, schema: dict, timeout: float | None = None) -> str:
        body = {"model": self.model, "stream": False, "format": schema, "keep_alive": "30m",
                "options": {"temperature": 0}, "messages": [
                    {"role": "system", "content": system}, {"role": "user", "content": user}]}
        reply = self.post(f"{self.url}/api/chat", body, timeout or self.timeout)
        try:
            return reply["message"]["content"]
        except (KeyError, TypeError):
            raise LlmUnavailable(f"unexpected answer from Ollama: {str(reply)[:200]}") from None

    def check(self, load_timeout: float = 120) -> None:
        """At startup: is Ollama running and the model pulled? Then load it, so the first call is fast."""
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=3) as resp:
                models = [m["name"] for m in json.loads(resp.read())["models"]]
        except (OSError, ValueError, KeyError):
            raise LlmUnavailable(f"Ollama is not running at {self.url}") from None
        if not any(m == self.model or m.split(":")[0] == self.model for m in models):
            raise LlmUnavailable(f"model {self.model} is not pulled (ollama pull {self.model})")
        self.complete("Answer with {}.", "warm up", {"type": "object"}, timeout=load_timeout)


def _post_json(url: str, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (OSError, ValueError) as e:  # URLError, timeouts, HTTP errors, bad JSON
        raise LlmUnavailable(f"Ollama: {e}") from None


if __name__ == "__main__":
    import sys

    from atc.intent.parser import parse


    model = sys.argv[1] if len(sys.argv) > 1 else "llama3.2"
    backend = OllamaBackend(model)
    t = time.perf_counter()
    backend.check()
    print(f"check + warm-up {time.perf_counter() - t:.1f} s")
    llm = LlmIntentParser(backend)
    ground = LlmContext("DLH4AB", "Lufthansa four Alfa Bravo", "Hamburg Ground", "clearance", ("05", "23", "15", "33"))
    cases = [
        (ground, "uh Hamburg ground Lufthansa four alpha bravo we would like to get our IFR clearance please, we have information bravo"),
        (ground, "we are on stand golf one and would like to start the engines, Lufthansa 4AB"),
        (ground, "Lufthansa 4AB, we are ready whenever you are at holding point two three"),
        (ground, "Hamburg ground, good afternoon, Lufthansa four alpha bravo, ready to copy"),
        (LlmContext("DLH4AB", "Lufthansa four Alfa Bravo", "Hamburg Approach", "climb", ("05", "23", "15", "33"),
                    last_atc="Lufthansa four Alfa Bravo, fly heading zero eight zero, climb altitude tree thousand fife hundred feet",
                    readback_expected=("heading", "altitude")),
         "heading zero eight zero, three thousand five hundred, Lufthansa 4AB"),
        (ground, "can we get a squawk please Lufthansa 4AB"),
    ]
    for ctx, text in cases:
        rule = parse(text, "DLH4AB")
        intent, note = llm.parse(text, ctx, rule.callsign)
        print(f"{text}\n   rule: {rule.kind}  |  {note}  |  addressed={intent and intent.addressed_to_us}")
