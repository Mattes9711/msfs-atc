"""Every call the ATC understands, in one list (step P1): what the pilot says, what ATC answers, what to read back.

The app's Phrases tab (P2) shows this list, sorted by phase, and the suggested next call comes from it too.
tests/test_catalog.py parses every pilot example and checks the intent and its values, so this help can never
promise a call the parser doesn't understand. When the parser learns a new call, add it here.

The phrases are our own, written after ICAO Doc 4444 / Doc 9432 and the German (DFS / VATSIM Germany) usage;
nothing is copied from those documents. Placeholders in braces are filled with the flight's values, or with
EXAMPLE when there is no flight:
    {station} {callsign} {destination} {atis} {runway} {squawk} {altitude} {level} {taxiways} {crossing}
    {frequency} {next_station} {qnh} {stand} {fix}
"""
from dataclasses import dataclass, field

# The order of the groups in the Phrases tab, with the controller phases each group belongs to
GROUPS = {
    "Clearance": ("clearance",),
    "Ground": ("cleared", "pushback", "taxi"),
    "Tower": ("taxi", "takeoff"),
    "Departure and Center": ("airborne", "climb", "enroute"),
    "Approach": ("arrival", "approach"),
    "Arrival Tower and Ground": ("final", "landing", "vacating", "taxi_in"),
    "Any time": (),
}

EXAMPLE = {
    "station": "Hamburg Ground", "callsign": "Lufthansa 4AB", "destination": "Munich", "atis": "alpha",
    "runway": "23", "squawk": "1701", "altitude": "5000 feet", "level": "flight level 350", "taxiways": "A, B",
    "crossing": "05", "frequency": "121.280", "next_station": "Hamburg Tower", "qnh": "1018", "stand": "G201",
    "fix": "AMLUH",
}


@dataclass(frozen=True)
class Phrase:
    group: str  # a key of GROUPS
    title: str  # "Request IFR clearance"
    pilot: str  # what the pilot says, with placeholders
    atc: str  # what ATC answers, in words (the real answer depends on the flight)
    kind: str  # the intent the parser must find
    items: dict = field(default_factory=dict)  # values the parser must find, keys of atc.intent.schema.ITEMS
    note: str = ""  # when to use it, what to watch for

    def text(self, values: dict | None = None) -> str:
        return self.pilot.format(**{**EXAMPLE, **(values or {})})


CORRECT = "\"readback correct\", or \"negative\" with what was wrong"  # ATC's answer to a readback

PHRASES = (
    # --- Clearance ---------------------------------------------------------------------------------------------
    Phrase("Clearance", "First call", "{station}, {callsign}",
           "\"{callsign}, {station}, go ahead\"", "checkin",
           note="Optional: you can also say your request right away."),
    Phrase("Clearance", "Request IFR clearance",
           "{station}, {callsign}, request IFR clearance to {destination}, information {atis}",
           "The clearance: destination, departure route, runway, initial climb, squawk", "request_clearance",
           {"atis": "a"}, note="Say the ATIS letter you listened to; with an old letter ATC gives you the new one."),
    Phrase("Clearance", "Read back the clearance",
           "Cleared to {destination}, runway {runway}, climb {altitude}, squawk {squawk}, {callsign}",
           CORRECT, "readback",
           {"runway": "23", "altitude_ft": 5000, "squawk": "1701"},
           note="Runway, altitude and squawk must be read back."),
    # --- Ground ------------------------------------------------------------------------------------------------
    Phrase("Ground", "Request pushback", "{station}, {callsign}, request push and start",
           "\"push and start approved\", or \"hold position, traffic passing behind\"", "request_pushback",
           note="With traffic taxiing behind the stand ATC holds the push and calls you when it has passed."),
    Phrase("Ground", "Answer a hold", "Holding position, {callsign}", "Nothing: ATC calls you when it is clear",
           "readback", {"hold_position": True},
           note="With strict readbacks a \"hold position\" must be read back like this."),
    Phrase("Ground", "Answer give way or follow", "Giving way to the Airbus, {callsign}", "Nothing", "acknowledge",
           note="The other traffic never waits for you: let it pass, or follow it. Also: \"following the Airbus\"."),
    Phrase("Ground", "Read back the pushback", "Push and start approved, facing east, {callsign}",
           "\"readback correct\"", "readback", {"pushback": True},
           note="\"Facing east\": after the push the nose points east. With strict readbacks it must be read back."),
    Phrase("Ground", "Pushback complete", "{station}, {callsign}, pushback complete",
           "\"roger, report ready for taxi\"", "checkin"),
    Phrase("Ground", "Request taxi", "{station}, {callsign}, request taxi",
           "The taxi route to the holding point, with every runway to hold short of", "request_taxi"),
    Phrase("Ground", "Request progressive taxi", "{station}, {callsign}, request progressive taxi",
           "The taxi route, then each turn shortly before it: \"turn left onto Bravo\"", "request_taxi",
           {"progressive": True},
           note="For an airport you don't know. Also while taxiing, from then on. Also to the stand after landing."),
    Phrase("Ground", "Off the cleared route", "Taxi to holding point runway {runway} via {taxiways}, {callsign}",
           CORRECT, "readback", {"runway": "23", "taxiways": ["A", "B"]},
           note="Ground: \"you appear to be on Bravo, new route, taxi to …\": read back the new route. "
                "Taxiing faster than about 30 knots gets \"reduce taxi speed\"."),
    Phrase("Ground", "Read back the taxi route",
           "Taxi to holding point runway {runway} via {taxiways}, hold short runway {crossing}, {callsign}",
           CORRECT, "readback",
           {"runway": "23", "taxiways": ["A", "B"], "hold_short": "05"},
           note="A hold short is always read back."),
    Phrase("Ground", "Holding short at a runway crossing", "{station}, {callsign}, holding short runway {crossing}",
           "\"cross runway {crossing}\"", "holding_short", {"hold_short": "05"},
           note="Stop at the hold short line first. Also: \"ready to cross runway 05\"."),
    Phrase("Ground", "Read back the crossing", "Crossing runway {crossing}, {callsign}",
           CORRECT, "readback", {"runway": "05"},
           note="Never enter a runway without a clearance: ATC calls \"stop immediately\"."),
    Phrase("Ground", "Check in with Ground after Apron", "{station}, {callsign}, with you",
           "\"continue taxi to holding point runway …\"", "checkin",
           note="At airports with an Apron frequency (e.g. Munich) Apron has you on the apron, then hands you over."),
    Phrase("Ground", "Read back a frequency change", "Contact {next_station} {frequency}, {callsign}",
           "A goodbye in the local language (\"tschüss\"), then switch and call the new controller", "readback",
           {"frequency_khz": 121280}),
    # --- Tower -------------------------------------------------------------------------------------------------
    Phrase("Tower", "Ready for departure", "{station}, {callsign}, holding point runway {runway}, ready for departure",
           "The takeoff clearance with the wind", "ready_departure", {"runway": "23"},
           note="Also: \"holding short runway 23, ready\". Without \"ready\": \"report when ready for departure\". "
                "With traffic ahead: \"behind the departing …, line up and wait\"; behind a heavier aircraft: "
                "\"expect departure in two minutes, wake turbulence\". ATC then calls you with the clearance."),
    Phrase("Tower", "Request line up", "{station}, {callsign}, request line up runway {runway}",
           "\"line up and wait runway …\"", "request_line_up",
           note="Line up and wait: onto the runway, but no takeoff yet. Then report ready."),
    Phrase("Tower", "Read back line up and wait", "Line up and wait runway {runway}, {callsign}",
           CORRECT, "readback", {"runway": "23", "line_up": True}),
    Phrase("Tower", "Intersection departure",
           "{station}, {callsign}, ready for departure from intersection B4",
           "The takeoff clearance \"from intersection …\"", "ready_departure", {"intersection": "B4"},
           note="Only from a taxiway that leads onto your runway; the runway ahead is shorter."),
    Phrase("Tower", "Wind check", "{station}, {callsign}, wind check", "The current wind", "request_wind",
           note="Also on final."),
    Phrase("Tower", "Read back the takeoff clearance", "Runway {runway}, cleared for takeoff, {callsign}",
           CORRECT, "readback", {"runway": "23", "cleared_takeoff": True}),
    # --- Departure and Center ----------------------------------------------------------------------------------
    Phrase("Departure and Center", "First call after takeoff",
           "{station}, {callsign}, passing 3000 feet climbing {altitude}",
           "\"radar contact\", a climb and a direct-to", "checkin",
           note="Say your altitude now and the one you climb to."),
    Phrase("Departure and Center", "Read back a climb and a direct-to", "Climb {level}, direct {fix}, {callsign}",
           CORRECT, "readback", {"flight_level": 350, "direct": "AMLUH"},
           note="A direct-to is a route clearance: read back the waypoint."),
    Phrase("Departure and Center", "Check in with Center", "{station}, {callsign}, {level}",
           "\"identified\", the rest of the climb and often a shortcut direct-to", "readback",
           {"flight_level": 350}),
    Phrase("Departure and Center", "Request higher", "{station}, {callsign}, request higher",
           "A climb to your cruise level", "request_level"),
    Phrase("Departure and Center", "Request a flight level", "{station}, {callsign}, request flight level 370",
           "\"climb\" or \"descend flight level 370\"", "request_level", {"flight_level": 370},
           note="Up to flight level 410."),
    Phrase("Departure and Center", "Request direct", "{station}, {callsign}, request direct {fix}",
           "\"proceed direct …\" if the point is ahead on your route", "request_direct", {"direct": "AMLUH"}),
    Phrase("Departure and Center", "Request descent", "{station}, {callsign}, request descent",
           "A descent and the QNH at the destination", "request_descent",
           note="ATC also starts the descent by itself at the top of descent."),
    Phrase("Departure and Center", "Read back a descent", "Descend flight level 100, {callsign}",
           CORRECT, "readback", {"flight_level": 100},
           note="With a SimBrief plan Center adds \"cleared … arrival\" (the STAR): say it in the readback too."),
    # --- Approach ----------------------------------------------------------------------------------------------
    Phrase("Approach", "First call to Approach", "{station}, {callsign}, descending flight level 100",
           "Altitude and QNH, a speed and a heading: radar vectors to the ILS", "readback", {"flight_level": 100}),
    Phrase("Approach", "Read back the vectors",
           "Descend {altitude}, QNH {qnh}, speed 220 knots, heading 230, {callsign}", CORRECT,
           "readback", {"altitude_ft": 5000, "qnh": 1018, "speed_kt": 220, "heading": 230},
           note="Fly the heading until the next instruction. Below 5000 feet (Germany) altitudes are on the QNH."),
    Phrase("Approach", "Read back the approach clearance",
           "Turn left heading 200, cleared ILS runway {runway}, speed 180 knots, {callsign}",
           CORRECT, "readback", {"heading": 200, "runway": "23", "speed_kt": 180},
           note="Intercept the localizer on that heading, then follow the glide slope down."),
    Phrase("Approach", "Established on the approach", "{station}, {callsign}, established ILS runway {runway}",
           "The handoff to Tower", "checkin", {"runway": "23"}),
    # --- Arrival Tower and Ground ------------------------------------------------------------------------------
    Phrase("Arrival Tower and Ground", "First call to Tower", "{station}, {callsign}, established ILS runway {runway}",
           "The landing clearance with the wind", "checkin", {"runway": "23"},
           note="With traffic ahead on final: \"continue approach, number two, traffic to follow …\"; the landing "
                "clearance comes by itself once it has landed and vacated."),
    Phrase("Arrival Tower and Ground", "Read back a speed reduction", "Reduce speed 160 knots, {callsign}",
           CORRECT, "readback", {"speed_kt": 160},
           note="Catching up with the traffic ahead (3 miles apart, more behind a heavy). \"Reduce to final approach "
                "speed\" needs no readback: fly your approach speed."),
    Phrase("Arrival Tower and Ground", "Read back the landing clearance",
           "Runway {runway}, cleared to land, {callsign}", CORRECT, "readback",
           {"runway": "23", "cleared_land": True}),
    Phrase("Arrival Tower and Ground", "Going around", "{station}, {callsign}, going around",
           "A heading and an altitude, then back to Approach", "going_around"),
    Phrase("Arrival Tower and Ground", "Runway vacated", "{station}, {callsign}, runway vacated",
           "The handoff to Ground", "vacated"),
    Phrase("Arrival Tower and Ground", "Request taxi to the gate", "{station}, {callsign}, request taxi to the gate",
           "The taxi route to your stand", "request_taxi"),
    Phrase("Arrival Tower and Ground", "Check in with Apron", "{station}, {callsign}, with you",
           "\"continue to stand …\"", "checkin", note="Ground hands you over to Apron at the apron, if there is one."),
    Phrase("Arrival Tower and Ground", "Read back the taxi route to the stand",
           "Taxi to stand {stand} via {taxiways}, {callsign}", CORRECT, "readback",
           {"taxiways": ["A", "B"]}),
    # --- Any time ----------------------------------------------------------------------------------------------
    Phrase("Any time", "Radio check", "{station}, {callsign}, radio check",
           "\"read you five\"", "radio_check"),
    Phrase("Any time", "Ask ATC to repeat", "{station}, {callsign}, say again",
           "The last transmission again", "say_again"),
    Phrase("Any time", "Wait a moment", "{station}, {callsign}, standby", "Nothing: ATC waits for your call",
           "acknowledge"),
    Phrase("Any time", "Can't comply", "Unable, {callsign}", "\"roger\": the instruction is withdrawn",
           "unable", note="Say what you can do instead, e.g. \"unable flight level 370, request flight level 330\"."),
    Phrase("Any time", "Request QNH", "{station}, {callsign}, request QNH", "The QNH: read it back", "request_qnh"),
    Phrase("Any time", "Request weather", "{station}, {callsign}, request weather at {destination}",
           "The destination's weather (wind, visibility, clouds, temperature, QNH)", "request_weather"),
    Phrase("Any time", "Confirm an instruction", "{station}, {callsign}, confirm cleared ILS runway {runway}",
           "\"affirm\", or \"negative\" with the right value", "confirm", {"runway": "23"},
           note="\"Confirm\" alone: ATC repeats its last transmission."),
    Phrase("Any time", "Answer traffic information", "Traffic in sight, {callsign}", "Nothing", "acknowledge",
           note="Or \"looking out\" while you search, \"negative contact\" if you can't see it."),
    Phrase("Any time", "Acknowledge", "Roger, {callsign}",
           "Nothing", "acknowledge", note="\"Wilco\" = will comply. Readbacks still need the values."),
)
