"""Cabin announcements (Milestone 7, C1): the purser speaks to the passengers at the moments of a flight.

Boarding, doors closed, climbing through 10000 ft, descent and arrival are said in the airline's home language first
(German for Lufthansa, Eurowings, Condor, …), then in English; airlines whose language has no texts yet get English
only. "Cabin crew, seats for take-off / landing" is a cockpit call to the crew and stays English. Cargo airlines carry
no passengers: no announcements.

The moments come from what ATC and the aircraft do (phase, altitude, the descent clearance); with GSX (C3) the
doors-closed announcement waits for its boarding to finish. Deterministic: each announcement once per flight.
"""
from dataclasses import dataclass

from atc.events import Event

CABIN = {"en": "Cabin", "de": "Kabine"}  # the "station" of an announcement: the voice picks its language from it
HOME_LANGUAGE = {code: "de" for code in ("DLH", "EWG", "CFG", "CLH", "TUI", "GWI", "AUA", "SWR", "EDW", "DLA")}
CARGO = {"BOX", "GEC", "FDX", "UPS", "CLX", "GTI", "CKS", "ABR", "BCS", "DHK"}
AIRLINE_NAME = {"DLH": "Lufthansa", "EWG": "Eurowings", "CFG": "Condor", "CLH": "Lufthansa CityLine",
                "TUI": "TUIfly", "GWI": "Germanwings", "AUA": "Austrian Airlines", "SWR": "Swiss",
                "EDW": "Edelweiss", "DLA": "Air Dolomiti", "BAW": "British Airways", "AFR": "Air France",
                "EZY": "easyJet", "EJU": "easyJet", "EZS": "easyJet", "RYR": "Ryanair", "KLM": "KLM",
                "UAE": "Emirates", "QTR": "Qatar Airways", "THY": "Turkish Airlines", "SAS": "SAS",
                "IBE": "Iberia", "VLG": "Vueling", "TAP": "TAP Air Portugal", "FIN": "Finnair", "LOT": "LOT",
                "WZZ": "Wizz Air", "AAL": "American Airlines", "DAL": "Delta", "UAL": "United"}
GERMAN_CITY = {"Munich": "München", "Cologne": "Köln", "Nuremberg": "Nürnberg", "Vienna": "Wien",
               "Zurich": "Zürich", "Geneva": "Genf", "Brussels": "Brüssel", "Milan": "Mailand", "Rome": "Rom",
               "Venice": "Venedig", "Prague": "Prag", "Warsaw": "Warschau", "Lisbon": "Lissabon",
               "Copenhagen": "Kopenhagen", "Athens": "Athen", "Moscow": "Moskau", "Hanover": "Hannover"}
CLIMB_FT = 10000
# Never right on top of the radio (the user's wish, 2026-11-16): a moment waits DELAY_S after it is due, and until
# the radio has been quiet for QUIET_S. The crew calls ("seats for take-off") are short and wait less.
DELAY_S, QUIET_S = 6, 10
CREW_CALLS = ("takeoff", "landing")
CREW_DELAY_S, CREW_QUIET_S = 0, 3

TEXTS = {
    "boarding": {
        "de": "Meine Damen und Herren, herzlich willkommen an Bord dieses {airline} Fluges nach {city}. Bitte "
              "verstauen Sie Ihr Handgepäck in den Fächern über Ihnen oder unter dem Sitz vor Ihnen. Vielen Dank.",
        "en": "Ladies and gentlemen, welcome on board this {airline} flight to {city}. Please stow your hand luggage "
              "in the overhead lockers or under the seat in front of you. Thank you.",
    },
    "doors": {
        "de": "Meine Damen und Herren, die Türen sind geschlossen. Bitte schalten Sie Ihre elektronischen Geräte in "
              "den Flugmodus, schnallen Sie sich an, und beachten Sie die folgenden Sicherheitshinweise.",
        "en": "Ladies and gentlemen, the doors are now closed. Please switch your electronic devices to flight mode, "
              "fasten your seatbelt, and pay attention to the following safety instructions.",
    },
    "takeoff": {"en": "Cabin crew, seats for take-off."},
    "climb": {
        "de": "Meine Damen und Herren, die Anschnallzeichen sind erloschen. Wir empfehlen Ihnen, auch am Platz "
              "angeschnallt zu bleiben. In Kürze beginnen wir mit unserem Service.",
        "en": "Ladies and gentlemen, the seatbelt signs are now off. We recommend that you keep your seatbelt "
              "fastened while seated. We will begin our service shortly.",
    },
    "descent": {
        "de": "Meine Damen und Herren, wir haben den Sinkflug nach {city} begonnen. Bitte kehren Sie zu Ihren Plätzen "
              "zurück, bringen Sie die Rückenlehne in eine aufrechte Position, klappen Sie die Tische hoch, und "
              "schnallen Sie sich an.",
        "en": "Ladies and gentlemen, we have started our descent to {city}. Please return to your seats, bring your "
              "seat back to the upright position, stow your tray tables, and fasten your seatbelt.",
    },
    "landing": {"en": "Cabin crew, seats for landing."},
    "arrival": {
        "de": "Meine Damen und Herren, willkommen in {city}. Bitte bleiben Sie angeschnallt, bis wir die "
              "Parkposition erreicht haben und die Anschnallzeichen erloschen sind. Vielen Dank, dass Sie "
              "{with_airline} geflogen sind, und einen schönen Tag.",
        "en": "Ladies and gentlemen, welcome to {city}. Please remain seated with your seatbelt fastened until we "
              "have reached our parking position and the seatbelt signs are off. Thank you for flying "
              "{with_airline}, and have a nice day.",
    },
}
ORDER = ("boarding", "doors", "takeoff", "climb", "descent", "landing", "arrival")


@dataclass
class Cabin:
    airline: str  # ICAO code, "DLH"; "" for a registration
    destination: str | None  # city or airport name, "Munich"
    said: set[str]
    waiting: tuple[str, float] | None = None  # (moment, since when it is due), while it waits for its turn

    @classmethod
    def for_flight(cls, callsign: str, destination: str | None) -> "Cabin":
        code = callsign[:3].upper() if len(callsign) > 3 and callsign[:3].isalpha() and callsign[3].isdigit() else ""
        return cls(code, destination, set())

    @property
    def silent(self) -> bool:
        return self.airline in CARGO

    def announce(self, moment: str) -> list[Event]:
        """The announcement for that moment, home language first, once per flight."""
        if self.silent or moment in self.said:
            return []
        self.said.add(moment)
        languages = [lang for lang in (HOME_LANGUAGE.get(self.airline), "en") if lang and lang in TEXTS[moment]]
        events = []
        airline = AIRLINE_NAME.get(self.airline, "")  # empty for a private flight: "this flight", "with us"
        for lang in dict.fromkeys(languages):
            city = self.destination or ("Ihrem Ziel" if lang == "de" else "your destination")
            if lang == "de":
                city = GERMAN_CITY.get(city, city)
                with_airline = f"mit {airline}" if airline else "mit uns"
            else:
                with_airline = airline or "with us"
            text = TEXTS[moment][lang].format(airline=airline, city=city, with_airline=with_airline)
            events.append(Event("cabin", " ".join(text.split()), CABIN[lang]))
        return events

    def check(self, phase: str, on_ground: bool, alt_msl_ft: float, descent_given: bool,
              boarding_done: bool | None = None, now: float | None = None,
              last_radio: float | None = None) -> list[Event]:
        """The announcement due now. boarding_done: GSX's boarding state (C3); None without GSX. With GSX the
        welcome and the doors wait for its boarding to be done. `now` (the live clock) and `last_radio` (when the
        last transmission was) hold it back a little and off the radio; without `now` it comes at once."""
        due = []
        before_departure = on_ground and phase in ("clearance", "cleared", "pushback", "taxi")
        if boarding_done is None:
            if phase in ("clearance", "cleared") and on_ground:
                due.append("boarding")
            if phase in ("pushback", "taxi"):
                due.append("doors")
        elif boarding_done and before_departure:
            due += ["boarding", "doors"]
        if phase == "takeoff":
            due.append("takeoff")
        if not on_ground and alt_msl_ft >= CLIMB_FT and phase in ("climb", "enroute"):
            due.append("climb")
        if descent_given:
            due.append("descent")
        if phase in ("final", "landing"):
            due.append("landing")
        if phase == "taxi_in":
            due.append("arrival")
        # in flight order: a late start must not say "welcome" after "descent"
        moment = next((m for m in ORDER if m in due and m not in self.said), None)
        if moment is None:
            self.waiting = None
            return []
        if now is not None:
            if self.waiting is None or self.waiting[0] != moment:
                self.waiting = (moment, now)
            delay, quiet = (CREW_DELAY_S, CREW_QUIET_S) if moment in CREW_CALLS else (DELAY_S, QUIET_S)
            if now - self.waiting[1] < delay or (last_radio is not None and now - last_radio < quiet):
                return []
        self.waiting = None
        return self.announce(moment)
