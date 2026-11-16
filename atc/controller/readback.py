"""Readback checking against the full ICAO list (Doc 4444 4.5.7.5): runway, hold short, taxi route, levels,
headings, speeds, squawk, frequencies, QNH, take-off/landing/line-up clearances.

An ATC instruction is a list of Items. Each item knows its value (to compare with the parsed readback)
and how ATC said it (to repeat it after "negative, I say again")."""
import difflib
from dataclasses import dataclass
from typing import Sequence

from atc.intent.schema import ITEMS
from atc.phraseology import spoken

READ_BACK_NAMES = {
    "runway": "runway", "hold_short": "hold short", "taxiways": "taxi route", "flight_level": "level",
    "altitude_ft": "altitude", "heading": "heading", "speed_kt": "speed", "squawk": "squawk",
    "frequency_khz": "frequency", "qnh": "QNH", "cleared_takeoff": "takeoff clearance",
    "cleared_land": "landing clearance", "line_up": "line up", "direct": "direct-to",
    "pushback": "pushback", "hold_position": "hold position",
}


@dataclass(frozen=True)
class Item:
    key: str
    value: object
    phrase: str  # e.g. "climb flight level one two zero"

    def __post_init__(self):
        if self.key not in READ_BACK_NAMES or not isinstance(self.value, ITEMS[self.key]):
            raise ValueError(f"not a readback item: {self.key}={self.value!r}")


@dataclass(frozen=True)
class ReadbackResult:
    wrong: tuple[Item, ...]
    missing: tuple[Item, ...]

    @property
    def ok(self) -> bool:
        return not self.wrong and not self.missing

    @property
    def correction(self) -> str | None:
        """What ATC says when the readback is not OK; None when it is."""
        parts = []
        if self.wrong:
            parts.append("negative, I say again, " + ", ".join(i.phrase for i in self.wrong))
        if self.missing:
            parts.append("read back " + spoken_list([READ_BACK_NAMES[i.key] for i in self.missing]))
        return ", ".join(parts) or None


def spoken_list(words: Sequence[str]) -> str:
    """'level', 'level and squawk', 'runway, altitude and squawk'."""
    return " and ".join(filter(None, [", ".join(words[:-1]), words[-1]])) if words else ""


def check_readback(issued: Sequence[Item], heard: dict) -> ReadbackResult:
    """Compare by value, never by wording: 'climb FL120' and 'up to one two zero' are the same readback."""
    wrong = tuple(i for i in issued if i.key in heard and not same(i.key, heard[i.key], i.value))
    missing = tuple(i for i in issued if i.key not in heard)
    return ReadbackResult(wrong, missing)


def same(key: str, heard, value) -> bool:
    """Equal, except a waypoint: whisper spells unknown names its own way ("Amlou" for AMLUH), so a close spelling of
    the direct-to fix counts."""
    if key == "direct" and isinstance(heard, str):
        return difflib.SequenceMatcher(None, heard.upper(), str(value).upper()).ratio() >= 0.7
    if key == "taxiways" and isinstance(heard, list) and len(heard) == len(value) + 1:
        return heard[:-1] == value  # "via E2, N4, N, A13": the holding point said once more at the end
    return heard == value


def instruction_text(items: Sequence[Item]) -> str:
    return ", ".join(i.phrase for i in items)


# Builders: one per kind of instruction, so the controller never assembles phrases by hand.

def level(fl: int, verb: str = "climb") -> Item:
    return Item("flight_level", fl, f"{verb} {spoken.flight_level(fl * 100)}")


def altitude(feet: int, verb: str = "climb") -> Item:
    return Item("altitude_ft", feet, f"{verb} altitude {spoken.altitude(feet)}")


def heading(degrees: int, turn: str | None = None) -> Item:
    return Item("heading", degrees, f"{f'turn {turn}' if turn else 'fly'} heading {spoken.heading(degrees)}")


def direct(fix: str) -> Item:
    """A route clearance, so it is read back (ICAO): 'proceed direct Lular'."""
    return Item("direct", fix, f"proceed direct {fix.title()}")


def pushback(facing: str | None) -> Item:
    """Read back only with strict readbacks: "push and start approved, facing west"."""
    return Item("pushback", True, "push and start approved" + (f", facing {facing}" if facing else ""))


def speed(knots: int) -> Item:
    return Item("speed_kt", knots, f"speed {spoken.speed(knots)}")


def squawk(code: str) -> Item:
    return Item("squawk", code, f"squawk {spoken.squawk(code)}")


def contact(station: str, khz: int) -> Item:
    return Item("frequency_khz", khz, f"contact {station} {spoken.frequency(khz)}")


def qnh(hpa: int) -> Item:
    return Item("qnh", hpa, f"QNH {spoken.qnh(hpa)}")


def taxi(runway: str, taxiways: Sequence[str] = (), hold_short: str | None = None,
         holding_point: str | None = None) -> list[Item]:
    point = f"{spoken.spell(holding_point)} " if holding_point else ""
    return [Item("runway", runway, f"taxi to holding point {point}runway {spoken.runway(runway)}"),
            *taxi_to_stand(taxiways, hold_short)]


def taxi_to_stand(taxiways: Sequence[str] = (), hold_short: str | None = None) -> list[Item]:
    """The readback part of 'taxi to stand X via A, B'; the stand itself isn't a readback item."""
    items = []
    if taxiways:
        items.append(Item("taxiways", list(taxiways), "via " + ", ".join(spoken.spell(t) for t in taxiways)))
    if hold_short:
        items.append(Item("hold_short", hold_short, f"hold short runway {spoken.runway(hold_short)}"))
    return items


def hold_position() -> Item:
    return Item("hold_position", True, "hold position")


def line_up(runway: str) -> list[Item]:
    return [Item("runway", runway, f"runway {spoken.runway(runway)}"), Item("line_up", True, "line up and wait")]


def cleared_takeoff(runway: str) -> list[Item]:
    return [Item("runway", runway, f"runway {spoken.runway(runway)}"),
            Item("cleared_takeoff", True, "cleared for takeoff")]


def cleared_land(runway: str) -> list[Item]:
    return [Item("runway", runway, f"runway {spoken.runway(runway)}"), Item("cleared_land", True, "cleared to land")]
