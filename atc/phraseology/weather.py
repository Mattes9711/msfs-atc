"""METAR elements in spoken form, for ATIS and weather information."""
import re

from atc.phraseology.spoken import digits, thousands_hundreds
from atc.weather.metar import Cloud

COVER = {"FEW": "few", "SCT": "scattered", "BKN": "broken", "OVC": "overcast", "VV": "vertical visibility"}
CLOUD_TYPE = {"CB": "cumulonimbus", "TCU": "towering cumulus"}
INTENSITY = {"-": "light", "+": "heavy"}
DESCRIPTOR = {"MI": "shallow", "BC": "patches of", "PR": "partial", "DR": "low drifting", "BL": "blowing",
              "SH": "showers", "TS": "thunderstorm", "FZ": "freezing"}
PHENOMENON = {"DZ": "drizzle", "RA": "rain", "SN": "snow", "SG": "snow grains", "IC": "ice crystals",
              "PL": "ice pellets", "GR": "hail", "GS": "small hail", "UP": "unknown precipitation", "BR": "mist",
              "FG": "fog", "FU": "smoke", "VA": "volcanic ash", "DU": "dust", "SA": "sand", "HZ": "haze",
              "PY": "spray", "PO": "dust whirls", "SQ": "squalls", "FC": "funnel cloud", "SS": "sandstorm",
              "DS": "duststorm"}


def visibility(metres: int) -> str:
    if metres >= 9999:
        return "visibility one zero kilometres or more"
    if metres >= 5000:
        return f"visibility {digits(metres // 1000)} kilometres"
    if metres < 100:
        return "visibility less than one hundred metres"
    return f"visibility {thousands_hundreds(metres // 100 * 100)} metres"


def cloud(c: Cloud) -> str:
    text = f"{COVER[c.cover]} {thousands_hundreds(c.base_ft) if c.base_ft else 'surface'} feet"
    return text + (f" {CLOUD_TYPE[c.type]}" if c.type else "")


def phenomenon(code: str) -> str:
    """'-SHRA' -> 'light rain showers', '+TSRA' -> 'heavy thunderstorm with rain', 'VCSH' -> 'showers in the vicinity'."""
    m = re.fullmatch(r"([-+]?)(VC)?(MI|BC|PR|DR|BL|SH|TS|FZ)?((?:[A-Z]{2})*)", code)
    if not m:
        return code
    intensity, vicinity, descriptor, rest = m.groups()
    phenomena = " and ".join(PHENOMENON.get(rest[i:i + 2], rest[i:i + 2]) for i in range(0, len(rest), 2))
    if descriptor == "SH":
        words = f"{phenomena} showers" if phenomena else "showers"
    elif descriptor == "TS":
        words = "thunderstorm" + (f" with {phenomena}" if phenomena else "")
    elif descriptor:
        words = f"{DESCRIPTOR[descriptor]} {phenomena}"
    else:
        words = phenomena
    if intensity:
        words = f"{INTENSITY[intensity]} {words}"
    return words + (" in the vicinity" if vicinity else "")


def temperature(celsius: int) -> str:
    return ("minus " if celsius < 0 else "") + digits(abs(celsius))
