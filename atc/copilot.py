"""The co-pilot on the radio (Milestone 7, C2).

The pilot hands over the radio ("copilot, you have the radio", the window's button or /copilot) and takes it back
("I have the radio", /copilot off). While the co-pilot has it, he reads back every instruction, tunes COM1 after a
handoff and checks in, with a voice of his own. Since 2026-11-16 (the user's wish) he also makes the requests of
each phase by himself, when the aircraft shows it is ready (`request_due`): the clearance at once, the pushback
when the beacon is on (or GSX's boarding is done), taxi when the push is over and the aircraft stands still,
"holding short" and "ready for departure" when it stands at the crossing or the holding point, taxi to the gate
after vacating. "copilot, next call" (or /copilot next, or the button) still makes him say a call earlier.

What he says is the window's suggestion (atc/controller/suggest.py), so his calls are exactly what the parser and
the controller expect. Deterministic: same situation, same call.
"""
import re

from atc.controller.suggest import suggestion
from atc.sim import gsx as gsx_states

TAKE = re.compile(r"\b(?:co-?pilot|first officer)\b.*\byou have (?:the )?(?:radio|radios|comms)\b"
                  r"|\byou have (?:the )?(?:radio|radios|comms)\b")
GIVE_BACK = re.compile(r"\bi have (?:the )?(?:radio|radios|comms)\b")
NEXT = re.compile(r"\b(?:co-?pilot|first officer)\b.*\bnext call\b")
SPEAKER = "Copilot"
STILL_S = 5  # standing still this long: at the crossing, the holding point, after the push
QUIET_S = 4  # a request waits for this much quiet on the radio: not straight after "readback correct"


def command(text: str) -> str | None:
    """"on", "off" or "next" when the pilot talks to the co-pilot (not to ATC), else None."""
    t = text.lower()
    if GIVE_BACK.search(t):
        return "off"
    if TAKE.search(t):
        return "on"
    if NEXT.search(t):
        return "next"
    return None


def due(atc) -> dict | None:
    """What the co-pilot says by himself now: a readback heard on our frequency, or the check-in after a handoff
    (once COM1 is on the new frequency). None when nothing is due or it is the pilot's request."""
    s = suggestion(atc)
    if s is None:
        return None
    tuned = atc.state.com1_khz if atc.state else 0
    if s["title"] == "Read back" and atc.pending_heard and s["khz"] == tuned:
        return s
    if s["title"] == "Check in" and atc.call_next is not None and s["khz"] == tuned:
        return s
    return None


def frequency_to_tune(atc) -> int | None:
    """After a handoff (the "contact …" read back): the new controller's frequency, if COM1 isn't on it yet."""
    if atc.pending or atc.call_next is None or atc.state is None:
        return None
    khz = atc.call_next.freq.khz
    return khz if atc.state.com1_khz != khz else None


def request_due(atc, still_s: float, pushed: bool, gsx=None) -> dict | None:
    """The request the co-pilot makes by himself now, or None while the aircraft isn't ready for it.
    still_s: how long the aircraft has stood still; pushed: it moved since the pushback was approved;
    gsx: GSX's state (atc/sim/gsx.py), None without GSX."""
    s = suggestion(atc)
    state = atc.state
    if s is None or state is None or s["title"] in ("Read back", "Check in"):
        return None
    title, phase = s["title"], atc.phase
    if title == "Request IFR clearance":
        ready = True
    elif title == "Request pushback":
        ready = state.beacon or bool(gsx and gsx.boarding_done)
    elif title == "Request taxi" and phase == "pushback":
        ready = bool(gsx and gsx.departure == gsx_states.COMPLETED) or (pushed and still_s >= STILL_S)
    elif title in ("At the crossing", "Ready for departure"):
        ready = still_s >= STILL_S
    elif title == "Request taxi":  # after vacating the runway
        ready = True
    else:
        ready = False
    return s if ready else None


def next_call(atc) -> dict | None:
    """The call that is due, said on the pilot's "next call": any suggestion, requests included."""
    return suggestion(atc)
