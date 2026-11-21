"""Arrival procedures from Little Navmap's MSFS database: STARs, instrument approaches and their transitions, with
each leg's altitude constraint and speed limit (Milestone 10 A).

What ATC needs for a realistic arrival: which STAR fits the landing runway, which transition leads from the STAR's
last fix to the approach, where the transition ends in vectors (an "FM" leg: "from the fix, expect vectors"), and the
altitudes and speeds to give before each fix. Munich ILS 26R, transition LANDU: LANDU, DM411, DM422, DM429, then
vectors, DM438 at or above 5000 ft, GUDEG (the final approach fix, 5000 ft), the threshold.

How Little Navmap stores them: table `approach` holds STARs (type GPS, suffix "A"), SIDs (suffix "D", not read here)
and approaches (type ILS, RNAV, LOC, …, suffix none or "Z", "Y", …). A STAR has one row per runway it serves (LAND2B
for 26R and for 26L). `approach_leg` holds the legs (`is_missed` the missed approach), `transition` and
`transition_leg` the transitions, named after their first fix. Altitudes: "A" at, "+" at or above, "-" at or below,
"B" between (altitude1 the top, altitude2 the bottom). Speeds: only "-", at or below.

The legs' own coordinates (fix_laty, fix_lonx) are empty in Little Navmap's MSFS database (found 2026-11-21: all
443810 transition legs), so each fix is looked up by its ident and region in the tables `waypoint`, `vor` and `ndb`,
of several the one nearest the airport (terminal waypoints like DM429 exist once per airport). Without the positions
Approach never followed a transition and the STAR's "LANDU at or below FL100" never moved the descent.

LICENCE: the user's own database, read in place on their machine only; never shipped, nothing from it in the repo.
"""
import sqlite3
from dataclasses import dataclass

from atc.airport.geo import distance_nm

ALTITUDE = {"A": "at", "+": "at_or_above", "-": "at_or_below", "B": "between"}
FIX_TABLES = {"W": "waypoint", "TW": "waypoint", "V": "vor", "TV": "vor", "N": "ndb", "TN": "ndb"}
VECTORS = {"FM", "VM"}  # legs that end by "manual termination": the controller's vectors from there
APPROACH_TYPES = ("ILS", "RNAV", "LOC", "VORDME", "VOR", "NDBDME", "NDB")  # preferred in this order


@dataclass(frozen=True)
class Leg:
    ident: str  # the fix, "" for a leg without one (a course to intercept, a heading)
    lat: float | None
    lon: float | None
    path: str  # ARINC path terminator: "IF", "TF", "CF", "FM", "CI", …
    alt: str | None = None  # "at", "at_or_above", "at_or_below", "between"
    alt_ft: int | None = None  # the altitude; for "between" the top
    alt2_ft: int | None = None  # for "between" the bottom
    speed_kt: int | None = None  # at or below
    course: float | None = None  # magnetic, for legs flown on a course (FM, CF, CI)

    @property
    def vectors(self) -> bool:
        """From here the controller gives headings."""
        return self.path in VECTORS

    @property
    def floor_ft(self) -> int | None:
        """The lowest altitude allowed at the fix, if any."""
        if self.alt in ("at", "at_or_above"):
            return self.alt_ft
        return self.alt2_ft if self.alt == "between" else None

    @property
    def ceiling_ft(self) -> int | None:
        """The highest altitude allowed at the fix, if any."""
        return self.alt_ft if self.alt in ("at", "at_or_below", "between") else None


@dataclass(frozen=True)
class Transition:
    name: str  # its first fix: "LANDU"
    legs: tuple[Leg, ...]

    @property
    def vectors_from(self) -> Leg | None:
        """The fix the vectors start at (the fix of the first "FM" leg), or None when it is flown to the end."""
        return next((leg for leg in self.legs if leg.vectors), None)


@dataclass(frozen=True)
class Procedure:
    name: str  # a STAR's name ("LAND2B"), an approach's ARINC name ("I26R")
    kind: str  # "star" or "approach"
    runway: str | None  # the runway it is for; None: a STAR for all runways
    legs: tuple[Leg, ...]
    transitions: tuple[Transition, ...] = ()
    approach_type: str | None = None  # "ILS", "RNAV", …; None for a STAR
    suffix: str | None = None  # "Z", "Y" for several approaches of one type to one runway
    missed: tuple[Leg, ...] = ()

    @property
    def first_fix(self) -> str | None:
        return next((leg.ident for leg in self.legs if leg.ident), None)

    @property
    def last_fix(self) -> str | None:
        """For a STAR the fix it ends at, where an approach transition starts (MIQ for LAND2B)."""
        return next((leg.ident for leg in reversed(self.legs) if leg.ident and not leg.ident.startswith("RW")), None)

    @property
    def faf(self) -> Leg | None:
        """An approach's final approach fix: the fix after the intermediate fix the approach starts at (GUDEG after
        DM438 for ILS 26R). The database doesn't mark it, so this is the usual layout, not a certainty."""
        fixes = [leg for leg in self.legs if leg.ident and not leg.ident.startswith("RW")]
        if self.kind != "approach" or not fixes:
            return None
        return fixes[1] if len(fixes) > 1 and fixes[0].path == "IF" else fixes[0]

    def transition(self, fix: str) -> Transition | None:
        fix = fix.upper()
        return next((t for t in self.transitions if t.name == fix), None)

    def serves(self, runway: str) -> bool:
        return self.runway is None or self.runway == runway


@dataclass(frozen=True)
class Procedures:
    """An airport's arrival procedures."""
    airport: str
    stars: tuple[Procedure, ...]
    approaches: tuple[Procedure, ...]

    def star(self, name: str, runway: str | None = None) -> Procedure | None:
        """The STAR of this name, for the runway when it has one per runway."""
        named = [s for s in self.stars if s.name == name.upper()]
        return next((s for s in named if runway and s.serves(runway)), named[0] if named else None)

    def stars_for(self, runway: str) -> tuple[Procedure, ...]:
        return tuple(s for s in self.stars if s.serves(runway))

    def star_from(self, fix: str, runway: str) -> Procedure | None:
        """A STAR for the runway that starts at the fix (or has a transition from it): for "LANDU" and 26R
        LAND2B, for 08R LAND2A. Several: the one whose name starts like the fix's."""
        fix = fix.upper()
        found = [s for s in self.stars_for(runway) if s.first_fix == fix or s.transition(fix)]
        return min(found, key=lambda s: (not s.name.startswith(fix[:4]), s.name), default=None)

    def approach(self, runway: str, types: tuple[str, ...] = APPROACH_TYPES) -> Procedure | None:
        """The approach to fly to the runway: an ILS if there is one, else RNAV, …; of "Z" and "Y" the plain one,
        then "Z"."""
        found = [a for a in self.approaches if a.runway == runway and a.approach_type in types]
        return min(found, key=lambda a: (types.index(a.approach_type), a.suffix is not None,
                                         -(ord(a.suffix) if a.suffix else 0)), default=None)


def load_procedures(con: sqlite3.Connection, ident: str) -> Procedures:
    """The airport's STARs and approaches, with their transitions; empty when the database has none."""
    stars, approaches = [], []
    fixes = FixFinder(con, ident)
    rows = con.execute("select approach_id, type, suffix, runway_name, fix_ident, arinc_name from approach "
                       "where airport_ident = ? order by approach_id", (ident.upper(),)).fetchall()
    for r in rows:
        approach_id, kind, suffix, runway, fix_ident, arinc = (r[0], r[1], r[2], r[3] or None, r[4], r[5])
        if suffix == "D":
            continue  # a SID
        legs = con.execute("select * from approach_leg where approach_id = ? order by approach_leg_id",
                           (approach_id,)).fetchall()
        transitions = tuple(
            Transition(t[1], tuple(_leg(dict(row), fixes) for row in con.execute(
                "select * from transition_leg where transition_id = ? order by transition_leg_id", (t[0],))))
            for t in con.execute("select transition_id, fix_ident from transition where approach_id = ? "
                                 "order by transition_id", (approach_id,)))
        common = tuple(_leg(dict(row), fixes) for row in legs if not row["is_missed"])
        missed = tuple(_leg(dict(row), fixes) for row in legs if row["is_missed"])
        if suffix == "A":
            stars.append(Procedure(fix_ident, "star", runway, common, transitions))
        else:
            approaches.append(Procedure(arinc or fix_ident, "approach", runway, common, transitions, kind, suffix,
                                        missed))
    return Procedures(ident.upper(), tuple(stars), tuple(approaches))


class FixFinder:
    """Where a procedure's fix is: by ident and region in the navaid tables, of several the nearest to the airport.
    None when the database doesn't have it (an old one without the tables, a fix of another kind)."""

    def __init__(self, con: sqlite3.Connection, airport: str):
        self.con, self.found = con, {}
        try:
            row = con.execute("select laty, lonx from airport where ident = ?", (airport.upper(),)).fetchone()
        except sqlite3.OperationalError:
            row = None
        self.near = (row[0], row[1]) if row else None

    def position(self, kind: str | None, ident: str, region: str | None) -> tuple[float, float] | None:
        tables = [FIX_TABLES[kind]] if kind in FIX_TABLES else ["waypoint", "vor", "ndb"]
        key = (tuple(tables), ident, region)
        if key not in self.found:
            self.found[key] = self._look_up(tables, ident, region)
        return self.found[key]

    def _look_up(self, tables: list[str], ident: str, region: str | None) -> tuple[float, float] | None:
        rows = []
        for table in tables:
            try:
                rows += self.con.execute(f"select laty, lonx, region from {table} where ident = ?", (ident,)).fetchall()
            except sqlite3.OperationalError:
                continue  # no such table
        if region and any(r[2] == region for r in rows):
            rows = [r for r in rows if r[2] == region]
        if not rows:
            return None
        if self.near is None:
            return rows[0][0], rows[0][1]
        best = min(rows, key=lambda r: distance_nm(r[0], r[1], *self.near))
        return best[0], best[1]


def _leg(row: dict, fixes: FixFinder | None = None) -> Leg:
    ident = row.get("fix_ident") or ""
    alt = ALTITUDE.get(row.get("alt_descriptor") or "")
    alt1, alt2 = row.get("altitude1") or 0, row.get("altitude2") or 0
    position = None
    if ident and (row.get("fix_laty") or row.get("fix_lonx")):
        position = (row["fix_laty"], row["fix_lonx"])
    elif ident and fixes is not None and row.get("fix_type") != "R":  # a runway's threshold is not a navaid
        position = fixes.position(row.get("fix_type"), ident, row.get("fix_region") or None)
    return Leg(
        ident=ident,
        lat=position[0] if position else None,
        lon=position[1] if position else None,
        path=row.get("type") or "",
        alt=alt if alt and alt1 else None,
        alt_ft=round(alt1) if alt and alt1 else None,
        alt2_ft=round(alt2) if alt == "between" and alt2 else None,
        speed_kt=row.get("speed_limit") or None,
        course=row.get("course") if row.get("type") in ("FM", "VM", "CF", "CI", "VI", "CA", "VA") else None,
    )
