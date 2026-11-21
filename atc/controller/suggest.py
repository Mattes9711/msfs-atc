"""What the pilot could say next (step P2, was A5), and the phrase book with the flight's own values.

Both only read the controller's state and are deterministic, like the controller itself:
- suggestion(): after an instruction, the readback with exactly the values to read back; otherwise the next call
  of the flight in standard phraseology ("Hamburg Ground, Lufthansa 4AB, request taxi").
- phrase_book(): the catalogue (atc/phraseology/catalog.py) with the flight's stations, runway, ATIS letter, ...
  filled in, and the group of the current phase marked.
The texts are what the pilot *writes or says*, so numbers are digits ("flight level 350"), not "tree fife zero".
tests/test_suggest.py flies a whole flight by saying only the suggestions.
"""
import re

from atc.airport.geo import bearing_deg, distance_nm
from atc.controller import readback as rb
from atc.controller.circuit import circuit_side, leg_words
from atc.controller.vfr import COMPASS as DIRECTIONS, point_written, zone_point
from atc.phraseology import spoken
from atc.phraseology.airlines import TELEPHONY
from atc.phraseology.catalog import EXAMPLE, GROUPS, PHRASES
from atc.controller.common import DESCENT_REQUEST_NM, PHASES

SPOKEN_DIGIT = r"(?:zero|one|two|tree|three|four|fife|five|six|seven|eight|niner|nine)"
# Which controller "{station}" is in each group of the phrase book
COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")
GROUP_ROLE = {"Clearance": "clearance", "Ground": "ground", "Tower": "tower", "Departure and Center": "departure",
              "Approach": "approach", "Arrival Tower and Ground": "arrival_tower"}
INFO_GROUP = "Small field (Info)"
ZONE_GROUP = "Control zone (VFR)"


def written_callsign(callsign: str, short: bool = False) -> str:
    """'DLH4AB' → 'Lufthansa 4AB', as the pilot says it (the parser reads both forms). A registration in phonetic
    words, 'Delta Mike Alfa Bravo Charlie', or with `short` 'Delta Bravo Charlie' (only once the controller used
    it: Controller.short_form_used)."""
    if spoken.registration(callsign):
        return spoken.short_callsign(callsign) if short else spoken.callsign(callsign)
    m = re.fullmatch(r"([A-Z]{3})(\d[A-Z0-9]*)", callsign.upper())
    return f"{TELEPHONY[m[1]]} {m[2]}" if m and m[1] in TELEPHONY else callsign.upper()


def _callsign_for(atc, station) -> str:
    return written_callsign(atc.plan.callsign, atc.short_form_used(station))


def readback_part(item: rb.Item) -> str:
    """One instruction item as the pilot reads it back."""
    key, value, phrase = item.key, item.value, item.phrase
    if key == "runway":
        before = phrase.split("runway")[0].strip()  # "taxi to holding point", "cross", "cleared ILS approach", ""
        before = {"cross": "crossing"}.get(before, before)
        if before.startswith("taxi to holding point"):  # named: "taxi to holding point B1" came with its own item
            before = "" if before != "taxi to holding point" else before
        return f"{before} runway {value}".strip()
    if key == "holding_point":
        return f"taxi to holding point {value}"
    if key == "hold_short":
        return f"hold short runway {value}"
    if key == "taxiways":
        return "via " + ", ".join(value)
    if key == "flight_level":
        return f"{phrase.split()[0]} flight level {value:03d}"
    if key == "altitude_ft":
        if phrase.endswith("or below"):  # in a control zone (Milestone 9 E)
            return f"{value} feet or below"
        return f"{phrase.split()[0]} {value} feet"
    if key == "vfr_point":  # "leave the control zone via November", "... to the north"
        if value.lower() in DIRECTIONS:
            return phrase
        head, _, tail = phrase.partition(" via ")
        exit_ = tail.partition(" and ")[2]  # crossing: "via Sierra and November" (E3)
        return f"{head} via {point_written(value)}" + (f" and {_digits(exit_)}" if exit_ else "")
    if key == "heading":
        return f"{phrase.split('heading')[0].strip()} heading {value:03d}".strip()
    if key == "pushback":
        return item.phrase  # "push and start approved, facing west": nothing spelled out in it
    if key == "direct":
        return f"direct {value}"
    if key == "speed_kt":
        return f"speed {value} knots"
    if key == "squawk":
        return f"squawk {value}"
    if key == "frequency_khz":
        m = re.match(rf"contact (.+?) {SPOKEN_DIGIT}\b", phrase)
        return f"contact {m[1] if m else 'the next controller'} {value / 1000:.3f}"
    if key == "qnh":
        return f"QNH {value}"
    # The rest are said as ATC said them; an item without an entry here falls back to ATC's words, never fails:
    # a KeyError here (hold_position, 2026-11-18) stopped push-to-talk, as the whisper prompt is built from this
    return {"cleared_takeoff": "cleared for takeoff", "cleared_land": "cleared to land",
            "line_up": "line up and wait", "hold_position": "hold position"}.get(key, item.phrase)


def _digits(words: str) -> str:
    """"Sierra one" → "Sierra 1", as the pilot writes a point."""
    digits = {w: str(i) for i, w in enumerate(("zero", "one", "two", "tree", "four", "fife", "six", "seven",
                                                "eight", "niner"))}
    return re.sub(r"(\d) (?=\d)", r"\1", " ".join(digits.get(w, w) for w in words.split()))


def suggestion(atc) -> dict | None:
    """{"title", "text", "station", "khz"} or None when nothing is due (e.g. taxiing, cruising). `station` is who
    to say it to: a readback goes to the controller who gave the instruction, even a "contact …"."""
    if atc.pending and (waiting := atc.readback_station()):
        cs = _callsign_for(atc, waiting)
        parts = [atc.readback_lead] if atc.readback_lead else []
        parts += [readback_part(i) for i in atc.pending]
        return {"title": "Read back", "text": ", ".join(parts) + f", {cs}",
                "station": waiting.name, "khz": waiting.freq.khz}
    if field := atc.crossing_ahead():
        return _crossing_suggestion(atc, field)  # a control zone on the way (Milestone 9 E3)
    if atc._ctr_role():
        return _ctr_suggestion(atc)  # through a control zone (Milestone 9 E)
    if role := atc._info_role():
        return _info_suggestion(atc, role)
    station = atc.expected_station()
    if station is None:
        return None
    cs = _callsign_for(atc, station)
    name, phase, state = station.name, atc.phase, atc.state

    def call(title: str, text: str) -> dict:
        return {"title": title, "text": f"{name}, {cs}, {text}", "station": name, "khz": station.freq.khz}

    if atc.call_next is not None and atc.call_next.key == station.key:  # just handed over: check in
        if phase in ("climb", "airborne") and state:
            passing = f"passing {round(state.alt_msl_ft, -2):.0f} feet"
            return call("Check in", f"{passing}, climbing {_level_text(atc)}" if atc.cleared_level else passing)
        if phase == "enroute":
            return call("Check in", _level_text(atc))
        if phase == "arrival":
            return call("Check in", f"descending {_level_text(atc)}")
        if phase == "final":
            return call("Check in", f"established ILS runway {atc.arrival_runway}")
        if phase == "vacating":
            return call("Request taxi", "request taxi to the gate")
        return call("Check in", "with you")
    if (phase in ("climb", "enroute") and not atc.descent_given and state and atc.destination
            and atc.descent_due_in_nm(state) <= DESCENT_REQUEST_NM):
        return call("Request descent", "request descent")  # the FMC's top of descent may come first
    if phase == "clearance":
        letter = spoken.ALPHABET[atc.atis.letter].lower()
        to = atc.destination.name if atc.destination else atc.plan.destination
        return call("Request IFR clearance",
                    f"request IFR clearance to {to}, information {letter}" if to else
                    f"request IFR clearance, information {letter}")
    if phase == "cleared" and atc.vfr:  # VFR: no clearance, no pushback; the first call says who we are (A3)
        to = atc.destination.name if atc.destination else atc.plan.destination
        letter = spoken.ALPHABET[atc.atis.letter].lower()
        parts = [atc.plan.aircraft, f"VFR to {to}" if to else "VFR", f"information {letter}", "request taxi"]
        return call("Request taxi", ", ".join(p for p in parts if p))
    if phase == "cleared":
        return call("Request pushback", "request push and start")
    if phase == "pushback":
        return call("Request taxi", "request taxi")
    if phase == "taxi":
        if crossing := atc.next_crossing_here():
            return call("At the crossing", f"holding short runway {crossing}")
        if atc.at_holding_point or atc.at_departure_holding_point() or atc.lined_up:
            return call("Ready for departure", f"holding point runway {atc.runway}, ready for departure")
        return None
    if phase == "arrival":
        return call("Check in", f"descending {_level_text(atc)}")
    if phase == "final":
        return call("Check in", f"established ILS runway {atc.arrival_runway}")
    if phase == "vacating":
        return call("Request taxi", "request taxi to the gate")
    if phase == "taxi_in" and (crossing := atc.next_crossing_here()):
        return call("At the crossing", f"holding short runway {crossing}")
    return None


def _ctr_suggestion(atc) -> dict | None:
    """VFR through a control zone (Milestone 9 E): the reporting point, the inbound call with the ATIS letter, the
    circuit reports to Tower."""
    station, state = atc.station(atc._ctr_role()), atc.state
    if station is None or state is None or state.on_ground:
        return None
    name, cs = station.name, _callsign_for(atc, station)

    def call(title: str, text: str) -> dict:
        return {"title": title, "text": f"{name}, {cs}, {text}", "station": name, "khz": station.freq.khz}

    stage, point = atc.ctr_stage, atc.ctr_point
    if stage == "out":
        if atc.phase == "takeoff":
            return None
        if point and point.point:
            return call("Reporting point", point_written(point.code))
        return call("Leaving the control zone", "leaving the control zone")
    dest, runway = atc.destination, atc.arrival_runway
    if stage is None:
        nm = round(distance_nm(dest.lat, dest.lon, state.lat, state.lon))
        side = COMPASS[round(bearing_deg(dest.lat, dest.lon, state.lat, state.lon) / 45) % 8]
        has_atis = atc.dest_atis and any(f.type == "ATIS" for f in dest.frequencies)
        letter = f"information {spoken.ALPHABET[atc.dest_atis.letter].lower()}" if has_atis else None
        parts = [f"{nm} miles {side}", f"{round(state.alt_msl_ft, -2):.0f} feet", letter, "for landing"]
        return call("Inbound", ", ".join(p for p in parts if p))
    if stage == "in":
        return call("Reporting point", f"overhead {point_written(point.code)}")
    if stage == "joining":
        return call("Downwind", f"{leg_words('downwind', circuit_side(dest, runway))} runway {runway}")
    if stage == "final_due":
        return call("On final", f"final runway {runway}")
    return None


def _crossing_suggestion(atc, field) -> dict | None:
    """Through another field's zone (E3): the request, then the points to report."""
    station, state = atc._zone_tower(field), atc.state
    if station is None or state is None:
        return None
    name, cs = station.name, _callsign_for(atc, station)

    def call(title: str, text: str) -> dict:
        return {"title": title, "text": f"{name}, {cs}, {text}", "station": name, "khz": station.freq.khz}

    if atc.ctr_stage == "crossing":
        point = atc.ctr_point
        if point.point:
            return call("Reporting point", point_written(point.code))
        return call("Leaving the control zone", "leaving the control zone")
    dest = atc.destination
    entry, exit_ = zone_point(field, state.lat, state.lon), zone_point(field, dest.lat, dest.lon)
    how = (f"from {point_written(entry.code)} to {point_written(exit_.code)}" if entry.point and exit_.point
           else f"from the {entry.words} to the {exit_.words}")
    nm = round(distance_nm(field.lat, field.lon, state.lat, state.lon))
    side = COMPASS[round(bearing_deg(field.lat, field.lon, state.lat, state.lon) / 45) % 8]
    return call("Request crossing", f"{nm} miles {side}, {round(state.alt_msl_ft, -2):.0f} feet, request crossing "
                                    f"of the control zone {how}")


def _info_suggestion(atc, role: str) -> dict | None:
    """At an uncontrolled field (Milestone 9 B): the calls to its Info, or the blind calls "Uetersen traffic, ..."
    where it has none, on the frequency tuned: the data has no frequency of its own for such a field (its UNICOM
    entry is the area's FIS, Langen Information in Germany)."""
    airport = atc.airport if role == "info" else atc.destination
    station = atc.station(role)
    if station is not None:
        name, khz, cs = station.name, station.freq.khz, _callsign_for(atc, station)
    elif atc.state is not None:
        name, khz, cs = f"{airport.name} traffic", atc.state.com1_khz, written_callsign(atc.plan.callsign)
    else:
        return None
    blind, phase, state = station is None, atc.phase, atc.state

    def call(title: str, text: str) -> dict:
        return {"title": title, "text": f"{name}, {cs}, {text}", "station": name, "khz": khz}

    if role == "info":
        runway = atc.runway
        if phase in ("clearance", "cleared", "pushback"):
            if blind:
                return call("Taxi", f"taxiing to runway {runway}")
            to = atc.destination.name if atc.destination else atc.plan.destination
            parts = [atc.plan.aircraft, "at the apron", f"VFR to {to}" if to else "VFR", "request taxi information"]
            return call("Request taxi information", ", ".join(p for p in parts if p))
        if phase == "taxi":
            return call("Departure", f"departing runway {runway}" if blind else f"ready for departure runway {runway}")
        if phase in ("climb", "enroute"):
            return call("Leaving the circuit", "leaving the circuit" if blind else
                        "leaving the circuit, leaving the frequency")
        return None
    runway = atc.arrival_runway
    local = airport.ident == atc.airport.ident  # a local flight: circuits at the home field (C3)
    if PHASES.index(phase) < PHASES.index("approach") and state is not None and not state.on_ground:
        if local:
            return None  # still climbing out: the crosswind turn puts it into the circuit
        nm = round(distance_nm(airport.lat, airport.lon, state.lat, state.lon))
        side = COMPASS[round(bearing_deg(airport.lat, airport.lon, state.lat, state.lon) / 45) % 8]
        where = f"{nm} miles {side}, {round(state.alt_msl_ft, -2):.0f} feet"
        return call("Inbound", f"{where}, joining the circuit runway {runway}" if blind else
                    f"{where}, for landing")
    if phase == "approach":
        leg = atc._own_leg(state)
        if leg in ("downwind", "base") and leg not in atc.circuit_reported:
            return call(leg.capitalize(), f"{leg_words(leg, circuit_side(airport, runway))} runway {runway}")
        final = f"final runway {runway}" if blind else f"on final runway {runway}"
        return call("On final", f"{final}, {'touch and go' if local else 'full stop'}")
    if phase == "vacating" or (phase == "landing" and state is not None and state.on_ground):
        return call("Runway vacated", "runway vacated")
    return None


def _level_text(atc) -> str:
    level = atc.cleared_level or ""
    if level.startswith("FL"):
        return f"flight level {level[2:]}"
    return level.replace(" FT", " feet")


def phrase_book(atc) -> list[dict]:
    """The catalogue by group, filled with this flight's values; the current phase's group first."""
    values = {"callsign": written_callsign(atc.plan.callsign), "runway": atc.runway,
              "atis": spoken.ALPHABET[atc.atis.letter].lower()}
    if atc.destination:
        values["destination"] = atc.destination.name
    if atc.squawk:
        values["squawk"] = atc.squawk
    if atc.cleared_level:
        values["level"] = _level_text(atc) if atc.cleared_level.startswith("FL") else EXAMPLE["level"]
    if atc.metar and atc.metar.qnh_hpa:
        values["qnh"] = str(atc.metar.qnh_hpa)
    info_role = atc._info_role()  # at a small field: its Info group is the current one (Milestone 9 C)
    if info_role:
        info = atc.station(info_role)
        field = atc.airport if info_role == "info" else atc.destination
        values["info"] = info.name if info else f"{field.name} traffic"
    zone_role = atc._ctr_role()  # through a control zone: its group is the current one (Milestone 9 E)
    zone_role = zone_role or ("crossing" if atc.crossing_ahead() else None)  # ... or one on the way (E3)
    groups = []
    for group, phases in GROUPS.items():
        role = GROUP_ROLE.get(group)
        station = atc.station(role) if role else atc.expected_station()
        filled = {**values, "station": station.name} if station else values
        arriving = group in ("Approach", "Arrival Tower and Ground") or (group == INFO_GROUP
                                                                          and info_role == "arrival_info") or (
            group == ZONE_GROUP and zone_role == "arrival_tower")
        if arriving and atc.arrival_runway:
            filled = {**filled, "runway": atc.arrival_runway}
        if info_role:
            current = group == INFO_GROUP
        elif zone_role:
            current = group == ZONE_GROUP
        else:
            current = atc.phase in phases
        groups.append({
            "group": group, "current": current,
            "phrases": [{"title": p.title, "pilot": p.text(filled), "atc": p.atc.format(**{**EXAMPLE, **filled}),
                         "note": p.note} for p in PHRASES if p.group == group]})
    return sorted(groups, key=lambda g: not g["current"])  # stable: the rest keep the flight's order
