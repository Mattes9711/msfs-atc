"""What the flight screen shows besides the radio log (Milestone 5, R1): the airport with its frequencies, the
station to call next, the flight in one line. Only reads the controller, like suggest.py and mapdata.py."""
from atc.controller.common import best_frequency, labelled
from atc.flightplan.route import SID

# How the frequency list names each job, in the order a flight uses them
# Info: a small field's station (Milestone 9 B). UNICOM (UC) is left out: in the German data it is Langen FIS
SHORT = {"ATIS": "ATIS", "C": "DEL", "APRON": "APRON", "G": "GND", "T": "TWR", "D": "DEP", "A": "APP", "FSS": "INFO"}
# Who comes after whom in a flight (Center is left out: which one depends on where the aircraft is)
ROLE_AFTER = {"clearance": "apron", "apron": "ground", "ground": "tower", "tower": "departure",
              "departure": "approach", "center": "approach", "approach": "arrival_tower",
              "arrival_tower": "arrival_ground", "arrival_ground": "arrival_apron", "info": "arrival_info"}


def airport_panel(atc) -> dict:
    """The airport that matters now (origin until airborne, then the destination), one frequency per job."""
    airport = atc.current_airport()
    metar = atc.destination_metar if airport is atc.destination else atc.metar
    frequencies, seen = [], set()
    for role in SHORT:
        found = [f for f in airport.frequencies if f.role == role or (role == "ATIS" and f.type == "ATIS")]
        if found and role not in seen:
            seen.add(role)
            f = best_frequency(found, atc.vfr)  # the one ATC uses: the VFR Tower only for VFR flights
            frequencies.append({"label": labelled(SHORT[role], f), "khz": f.khz, "station": f.station or "ATIS"})
    wind = None
    if metar is not None and metar.wind_kt is not None:
        wind = "calm" if metar.wind_kt == 0 else \
            f"{'VRB' if metar.wind_dir is None else f'{metar.wind_dir:03.0f}'}/{metar.wind_kt:02d}"
    return {"ident": airport.ident, "name": airport.name, "frequencies": frequencies, "wind": wind,
            "qnh": metar.qnh_hpa if metar else None,
            "runway": atc.arrival_runway if airport is atc.destination else atc.runway}


def next_station(atc) -> dict | None:
    """NEXT in the radio box: the controller to call if it isn't tuned yet, else the one after it."""
    expected = atc.expected_station()
    tuned = atc.station_at(atc.state.com1_khz) if atc.state else None
    if expected is not None and (tuned is None or tuned.key != expected.key):
        return {"name": expected.name, "khz": expected.freq.khz}
    role = ROLE_AFTER.get(atc._phase_role())
    while role:  # skip roles the airport doesn't have, and the controller already tuned (Ground doing Delivery)
        station = atc.station(role)
        if station is not None and (tuned is None or station.key != tuned.key):
            return {"name": station.name, "khz": station.freq.khz}
        role = ROLE_AFTER.get(role)
    return None


def flight_line(atc) -> dict:
    route = atc.plan.route.upper().split()
    sid = atc.plan.sid or (route[0] if route and SID.fullmatch(route[0]) else None)
    return {"sid": sid, "star": atc.plan.star, "destination": atc.plan.destination}
