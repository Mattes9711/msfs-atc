"""What a pilot transmission means, as structured data. The rule parser fills it now; the LLM fallback (step 24)
must produce exactly this shape, so it is defined once here."""
from dataclasses import dataclass, field

KINDS = (
    "request_clearance", "request_pushback", "request_taxi", "request_descent", "request_other",
    "ready_departure", "holding_short", "request_line_up", "request_wind", "request_level", "request_direct", "request_qnh", "request_weather", "unable",
    "confirm", "going_around", "vacated", "checkin", "readback", "acknowledge",
    "leaving_frequency", "inbound", "on_final", "circuit_report",  # calls at a small field (Milestone 9 B, C)
    "point_report",  # over a visual reporting point, or leaving the control zone (Milestone 9 E)
    "request_crossing",  # "request crossing of the control zone from November to Sierra" (Milestone 9 E3)
    "radio_check", "say_again", "unknown",
)

# Item name -> type. Only these keys may appear in Intent.items.
ITEMS = {
    "runway": str,  # "23", "08L"
    "hold_short": str,  # runway designator
    "taxiways": list,  # ["A", "B3"]
    "flight_level": int,  # 120 = FL120
    "altitude_ft": int,
    "heading": int,
    "speed_kt": int,
    "squawk": str,  # four digits, kept as text: "0421"
    "frequency_khz": int,
    "qnh": int,
    "atis": str,  # single letter, "b"
    "cleared_takeoff": bool,
    "cleared_land": bool,
    "line_up": bool,
    "intersection": str,  # taxiway for an intersection departure, "B4"
    "direct": str,  # waypoint of a direct-to, "LULAR"
    "pushback": bool,  # "push and start approved" read back
    "hold_position": bool,  # "hold position" read back ("holding position")
    "progressive": bool,  # "request progressive taxi": Ground calls each turn
    "vfr_point": str,  # a visual reporting point: "N", "S1", "EWEST", or a direction out of the zone: "NORTH"
    "vfr_exit": str,  # crossing a control zone: the point to leave it by, "S" (the entry is vfr_point)
}


@dataclass(frozen=True)
class Intent:
    kind: str
    callsign: str | None  # as heard and normalised, e.g. "DLH4AB"; None if no callsign was found
    addressed_to_us: bool
    items: dict = field(default_factory=dict)
    text: str = ""  # normalised transmission, for display and debugging

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"unknown intent kind {self.kind!r}")
        for key, value in self.items.items():
            if key not in ITEMS or not isinstance(value, ITEMS[key]):
                raise ValueError(f"bad intent item {key}={value!r}")
