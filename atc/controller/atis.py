import string

from atc.airport.model import Airport
from atc.phraseology import spoken, weather
from atc.weather.metar import Metar

LETTERS = string.ascii_uppercase


class Atis:
    """The ATIS letter advances whenever the observation or the runway in use changes, so a pilot reporting an
    old letter can be told what is current."""

    def __init__(self, airport: Airport, first_letter: str = "A"):
        self.airport = airport
        self._index = LETTERS.index(first_letter) - 1
        self._key: tuple | None = None
        self.metar: Metar | None = None
        self.runway: str | None = None

    @property
    def letter(self) -> str:
        return LETTERS[self._index % 26]

    def update(self, metar: Metar | None, runway: str) -> bool:
        """Returns True when this produced a new ATIS letter."""
        key = (metar.raw if metar else None, runway)
        if key == self._key:
            return False
        self._key, self.metar, self.runway = key, metar, runway
        self._index = (self._index + 1) % 26
        return True

    def broadcast(self) -> str:
        letter = spoken.ALPHABET[self.letter]
        first = f"{self.airport.name} information {letter}"
        if self.metar:
            first += f", time {spoken.digits(self.metar.time[2:6])}"
        sentences = [first, f"Runway in use {spoken.runway(self.runway)}"]
        wx = _weather(self.metar) if self.metar else "no weather information available"
        sentences.append(wx[:1].upper() + wx[1:])
        sentences.append(f"Advise on initial contact you have information {letter}")
        return ". ".join(sentences) + "."


def weather_text(m: Metar) -> str:
    """The METAR as spoken: wind, visibility or CAVOK, weather, clouds, temperatures, QNH."""
    return _weather(m)


def _weather(m: Metar) -> str:
    parts = []
    if m.wind_kt is not None:
        parts.append(spoken.wind(m.wind_dir, m.wind_kt, m.gust_kt))
    if m.cavok:
        parts.append("cav okay")
    else:
        if m.visibility_m is not None:
            parts.append(weather.visibility(m.visibility_m))
        parts += [weather.phenomenon(w) for w in m.weather]
        parts += [weather.cloud(c) for c in m.clouds]
    if m.temp_c is not None:
        parts.append(f"temperature {weather.temperature(m.temp_c)}")
        if m.dewpoint_c is not None:
            parts.append(f"dew point {weather.temperature(m.dewpoint_c)}")
    if m.qnh_hpa is not None:
        parts.append(f"QNH {spoken.qnh(m.qnh_hpa)}")
    return ", ".join(parts)
