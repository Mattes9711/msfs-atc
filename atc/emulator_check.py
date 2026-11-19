"""Checks emulator logs against the checklist: what a flight with real ATC would not have sounded like.

    python -m atc.emulator_check                       every log in the logs folder, under "emulator"
    python -m atc.emulator_check --since 2026-11-19_2044   the logs from then on (the file names start with the time)
    python -m atc.emulator_check FILE ...              these logs

The emulator (atc/emulator.py) runs it after every flight it flies. A hit is a hint to read the log there, not a
finding: the emulator's own findings are K1.

| #   | Point                    | A hit                                                                            |
|-----|--------------------------|----------------------------------------------------------------------------------|
| K1  | Gate to gate             | Not finished, or the emulator's own findings                                     |
| K2  | No complaints            | ATC says "say again", "negative", "unable", "confirm", "stop immediately", "go around" |
| K3  | Runway against the wind  | Departure or landing runway with more than 5 kt tailwind                         |
| K4  | Clearance readback       | "cleared to ..." missing from the readback of the clearance                      |
| K5  | Handoffs                 | After "contact X ..." the next call goes to another station                      |
| K6  | Frequencies              | An airport station handed off to on a frequency not in the airport's list        |
| K7  | Digits spoken            | Arabic numerals in an ATC line                                                   |
| K8  | Altitude direction       | "climb" to below the aircraft, "descend" to above it                             |
| K9  | Vectors                  | Two headings within 30 s; "turn left" where the turn is to the right, or the other way round |
| K10 | Intercept                | The intercept heading more than 40 degrees off the runway (30, and 10 for the designator's rounding) |
| K11 | Landing clearance        | "cleared to land" under 2 nm from the field                                      |
| K12 | Tower handoff            | Approach hands over to Tower under 6 nm from the field                           |
| K13 | Taxi-in readback         | The stand (or parking) missing from the readback                                 |
| K14 | End                      | "flight complete" more than a minute before the aircraft is at the stand         |
| K15 | Waiting                  | Standing on the ground more than 2 minutes without a call                        |
| K16 | Center sequence          | Back to a sector already flown (ping-pong)                                       |
| K17 | Glide path               | More than 500 ft off at 10 nm, more than 250 ft at 5 nm                          |

Found with these checks on 2026-11-19: the runway choice against the wind, the missing clearance limit and stand
in the readbacks, a base turn just before the intercept, and the double crossing at EDDF.
"""
import argparse
import math
import re
import sys
from pathlib import Path

DIGITS = {"zero": "0", "one": "1", "two": "2", "tree": "3", "four": "4", "fife": "5", "six": "6", "seven": "7",
          "eight": "8", "niner": "9"}
CLOCK = r"(\d+):(\d\d):(\d\d)"
POS = re.compile(r"[\d.]+[NS] [\d.]+[EW], (?:(?P<alt>\d+) ft|(?P<ground>on the ground)), GS (?P<gs>\d+) kt, "
                 r"HDG (?P<hdg>\d+), (?P<phase>\w+), .*?(?P<nm>\d+) nm to \w+")


def seconds(h: str, m: str, s: str) -> int:
    return int(h) * 3600 + int(m) * 60 + int(s)


def turn(a: float, b: float) -> float:
    """From heading a to heading b: positive to the right, -180..180."""
    return (b - a + 540) % 360 - 180


def number(words: str) -> str:
    """"two tree zero" -> "230"; other words are left out."""
    return "".join(DIGITS[w] for w in words.split() if w in DIGITS)


def altitude_ft(text: str) -> int | None:
    """The altitude right after "climb"/"descend": "flight level one two zero", "altitude four thousand two hundred
    feet", "altitude fife thousand feet"."""
    if m := re.match(r"flight level ((?:\w+ ?){3})", text):
        return int(number(m[1]) or 0) * 100 or None
    if m := re.match(r"altitude ([a-z ]+?) thousand(?: (\w+) hundred)? feet", text):
        thousands = number(m[1])
        return int(thousands) * 1000 + int(number(m[2] or "") or 0) * 100 if thousands else None
    return None


def frequency(words: str) -> str | None:
    """"one two one decimal seven fife zero" -> "121.750"."""
    left, _, right = words.partition(" decimal ")
    return f"{number(left)}.{number(right):0<3}" if right else None


class Log:
    """An emulator log: the "# EMU" header, the report, and after "Radio:" the radio and POS lines."""

    def __init__(self, text: str):
        lines = text.splitlines()
        self.header = "\n".join(line[6:] for line in lines if line.startswith("# EMU "))
        self.report = "\n".join(line for line in lines if not line.startswith("# EMU ")).split("\nRadio:")[0]
        self.radio: list[tuple[int, str, str]] = []  # (s, kind, text): atc, copilot, notice, tuning, ...
        self.pos: list[tuple[int, re.Match]] = []
        radio = False
        for line in lines:
            radio = radio or line == "Radio:"
            m = re.match(r"\s*" + CLOCK + r"\s+(\S+)\s+(.*)", line) if radio else None
            if not m:
                continue
            t, kind, text = seconds(*m.groups()[:3]), m[4], m[5]
            if kind == "POS":
                if p := POS.match(text):
                    self.pos.append((t, p))
            else:
                self.radio.append((t, kind, text))

    def at(self, t: int) -> re.Match | None:
        """The last position at or before t."""
        before = [p for s, p in self.pos if s <= t]
        return before[-1] if before else None

    def atc(self):
        return [(t, x) for t, k, x in self.radio if k == "atc"]

    def readback(self, i: int) -> str:
        """The co-pilot's answer to radio line i."""
        return next((x for _, k, x in self.radio[i + 1:i + 3] if k == "copilot"), "")


def check(text: str) -> list[tuple[str, str]]:
    """(K-number, what) for every hit in a log."""
    log, hits = Log(text), []

    def hit(key, what):
        hits.append((key, what))

    # K1
    first = log.report.strip().splitlines()[0] if log.report.strip() else ""
    if "NOT finished" in first or not re.search(r"\b0 finding", first):
        findings = re.search(r"Findings:.*?(?=\n\n|\Z)", log.report, re.S)
        hit("K1", (first + (" | " + findings[0].replace("\n", " | ") if findings else ""))[:300])
    # K2
    for t, x in log.atc():
        if re.search(r"say again|negative|unable|confirm|stop immediately|go around", x):
            hit("K2", x[:160])
    # K3
    for label, wind_rx, runway_rx in (("departure", r"Weather: METAR (.*)", r"Runway in use: (\d\d)"),
                                      ("landing", r"Destination: .*?METAR (.*)", r"landing runway (\d\d)")):
        metar, runway = re.search(wind_rx, log.header), re.search(runway_rx, log.header)
        wind = re.search(r"\b(\d{3})(\d{2,3})(?:G\d+)?KT\b", metar[1]) if metar else None
        if wind and runway:
            head = int(wind[2]) * math.cos(math.radians(turn(int(runway[1]) * 10, int(wind[1]))))
            if head < -5:
                hit("K3", f"{label} runway {runway[1]}, wind {wind[1]}/{wind[2]}: {-head:.0f} kt tailwind")
    for i, (t, k, x) in enumerate(log.radio):
        if k != "atc":
            continue
        # K4
        if ", cleared to " in x and "squawk" in x and "cleared to" not in log.readback(i):
            hit("K4", f"readback '{log.readback(i)}'")
        # K13
        if m := re.search(r"taxi to (stand|parking)", x):
            if m[1] not in log.readback(i):
                hit("K13", f"readback '{log.readback(i)}'")
        # K5, K6
        if m := re.search(r"contact ([A-Z][\w ]+?) ((?:(?:zero|one|two|tree|four|fife|six|seven|eight|niner) ?)+"
                          r"decimal(?: (?:zero|one|two|tree|four|fife|six|seven|eight|niner))+)", x):
            name, freq = m[1], frequency(m[2])
            calls = [y for _, kk, y in log.radio[i + 1:] if kk == "copilot" and not y.startswith("contact ")]
            if calls and not calls[0].startswith(name):
                hit("K5", f"'contact {name} {freq}', then '{calls[0][:70]}'")
            listed = re.search(rf"(?:^|\| |: ){re.escape(name)} ([\d., ]+)", log.header, re.M)
            if listed and freq not in [f.strip() for f in listed[1].split(",")]:
                hit("K6", f"{name} on {freq}, listed {listed[1].strip()}")
        # K7
        if re.search(r"\d", x):
            hit("K7", x[:140])
        # K8
        p = log.at(t)
        if (m := re.search(r"\b(climb|descend) (flight level .*|altitude .*)", x)) and p and p["alt"]:
            ft, alt = altitude_ft(m[2]), int(p["alt"])
            if ft and ((m[1] == "climb" and ft < alt - 200) or (m[1] == "descend" and ft > alt + 200)):
                hit("K8", f"{m[1]} to {ft} ft at {alt} ft")
        # K9: the direction
        if (m := re.search(r"turn (left|right) heading ([a-z ]+?)(,|$)", x)) and p:
            heading, d = int(number(m[2])), turn(int(p["hdg"]), int(number(m[2])))
            if (m[1] == "left" and d > 10) or (m[1] == "right" and d < -10):
                hit("K9", f"turn {m[1]} heading {heading:03d} from {int(p['hdg']):03d}")
        # K11, K12
        if x.endswith("cleared to land") and p and int(p["nm"]) < 2:
            hit("K11", f"cleared to land {p['nm']} nm from the field")
        if re.search(r"contact \w+ Tower", x) and p and p["phase"] in ("approach", "final") and int(p["nm"]) < 6:
            hit("K12", f"Tower handoff {p['nm']} nm from the field")
    # K9: two headings close together
    vectors = [(t, x) for t, x in log.atc() if re.search(r"(turn (left|right)|fly) heading", x)]
    for (t1, x1), (t2, x2) in zip(vectors, vectors[1:]):
        if t2 - t1 < 30:
            hit("K9", f"{t2 - t1} s apart: '{x1.split(', ', 1)[-1][:50]}' / '{x2.split(', ', 1)[-1][:50]}'")
    # K10
    runway = re.search(r"landing runway (\d\d)", log.header)
    for t, x in log.atc():
        if runway and (m := re.search(r"heading ([a-z ]+?), maintain .* until established", x)):
            heading = int(number(m[1]))
            if abs(turn(int(runway[1]) * 10, heading)) > 40:
                hit("K10", f"intercept heading {heading:03d} for runway {runway[1]}")
    # K14
    complete = [t for t, k, x in log.radio if k == "notice" and x == "flight complete"]
    end = re.search(r"^\s+" + CLOCK + r"\s+end\b", log.report, re.M)
    if complete and end and complete[0] < seconds(*end.groups()) - 60:
        hit("K14", f"flight complete {seconds(*end.groups()) - complete[0]} s before the end")
    # K15: standing still on the ground the whole time between two calls
    talk = [t for t, k, x in log.radio if k in ("atc", "copilot")]
    for a, b in zip(talk, talk[1:]):
        during = [p for s, p in log.pos if a <= s <= b]
        if b - a > 120 and during and all(p["ground"] and int(p["gs"]) < 5 for p in during):
            hit("K15", f"{b - a} s without a call, standing, phase {during[0]['phase']}")
    # K16
    sectors = [m[1] for t, x in log.atc() if (m := re.search(r"contact (\w+ (?:Radar|Center|Control))", x))]
    for i, sector in enumerate(sectors):
        if sector in sectors[:i] and sector != sectors[i - 1]:
            hit("K16", " > ".join(sectors))
            break
    # K17
    for nm, limit in (("10", 500), ("5", 250)):
        m = re.search(rf"\b{nm} nm from the threshold: (\d+) ft above the field \(3 degrees: (\d+)\)", log.report)
        if m and abs(int(m[1]) - int(m[2])) > limit:
            hit("K17", m[0])
    return hits


def main(argv: list[str] | None = None) -> int:
    from atc import paths

    p = argparse.ArgumentParser(prog="python -m atc.emulator_check", description=__doc__.split("\n")[0])
    p.add_argument("files", nargs="*", help="logs to check (default: all in the logs folder)")
    p.add_argument("--since", default="", metavar="STAMP", help="only logs whose name is at or after this, "
                                                                "e.g. 2026-11-19_2044")
    args = p.parse_args(argv)
    files = [Path(f) for f in args.files] or sorted(
        f for f in (paths.logs_dir() / "emulator").glob("*_EMU.txt") if f.name >= args.since)
    by_key: dict[str, list[str]] = {}
    for f in files:
        for key, what in check(f.read_text(encoding="utf-8")):
            by_key.setdefault(key, []).append(f"{f.name.removesuffix('_EMU.txt')}: {what}")
    print(f"{len(files)} log(s), {sum(map(len, by_key.values()))} hit(s)")
    for key in sorted(by_key, key=lambda k: int(k[1:])):
        print(f"\n{key}: {len(by_key[key])}")
        for line in by_key[key][:12]:
            print("  " + line)
    return 1 if by_key else 0


if __name__ == "__main__":
    sys.exit(main())
