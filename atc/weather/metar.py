import re
from dataclasses import dataclass

KT_PER_MPS = 1.94384
HPA_PER_INHG = 33.8639
M_PER_SM = 1609.34

WIND = re.compile(r"(?P<dir>\d{3}|VRB)(?P<speed>\d{2,3})(?:G(?P<gust>\d{2,3}))?(?P<unit>KT|MPS)")
CLOUD = re.compile(r"(?P<cover>FEW|SCT|BKN|OVC|VV)(?P<base>\d{3})(?P<type>CB|TCU)?")
TEMP = re.compile(r"(?P<temp>M?\d{2})/(?P<dew>M?\d{2})?")
PHENOMENON = re.compile(
    r"[-+]?(VC)?(MI|BC|PR|DR|BL|SH|TS|FZ)?(DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+"
)
TREND_OR_REMARKS = {"RMK", "NOSIG", "BECMG", "TEMPO"}


@dataclass(frozen=True)
class Cloud:
    cover: str  # FEW, SCT, BKN, OVC, VV
    base_ft: int
    type: str | None  # CB, TCU


@dataclass(frozen=True)
class Metar:
    raw: str
    station: str
    time: str  # ddhhmmZ
    wind_dir: int | None  # degrees true; None = variable or missing
    wind_kt: int | None  # None = no wind group
    gust_kt: int | None
    visibility_m: int | None
    cavok: bool
    clouds: tuple[Cloud, ...]
    weather: tuple[str, ...]
    temp_c: int | None
    dewpoint_c: int | None
    qnh_hpa: int | None


def parse_metar(raw: str) -> Metar:
    tokens = raw.split()
    if tokens and tokens[0] in ("METAR", "SPECI"):
        tokens = tokens[1:]
    if len(tokens) < 2 or not re.fullmatch(r"[A-Z0-9]{4}", tokens[0]) or not re.fullmatch(r"\d{6}Z", tokens[1]):
        raise ValueError(f"not a METAR: {raw!r}")
    station, time = tokens[0], tokens[1]
    fields = dict(wind_dir=None, wind_kt=None, gust_kt=None, visibility_m=None, cavok=False,
                  temp_c=None, dewpoint_c=None, qnh_hpa=None)
    clouds, weather = [], []

    for token in tokens[2:]:
        if token in TREND_OR_REMARKS:
            break  # anything after this is a forecast or remark, not the current observation
        if m := WIND.fullmatch(token):
            factor = KT_PER_MPS if m["unit"] == "MPS" else 1
            fields["wind_dir"] = None if m["dir"] == "VRB" else int(m["dir"])
            fields["wind_kt"] = round(int(m["speed"]) * factor)
            fields["gust_kt"] = round(int(m["gust"]) * factor) if m["gust"] else None
        elif token == "CAVOK":
            fields["cavok"], fields["visibility_m"] = True, 10000
        elif re.fullmatch(r"\d{4}", token):
            fields["visibility_m"] = int(token)
        elif m := re.fullmatch(r"P?(\d+)SM", token):
            fields["visibility_m"] = round(int(m[1]) * M_PER_SM)
        elif m := CLOUD.fullmatch(token):
            clouds.append(Cloud(m["cover"], int(m["base"]) * 100, m["type"]))
        elif m := TEMP.fullmatch(token):
            fields["temp_c"] = _celsius(m["temp"])
            fields["dewpoint_c"] = _celsius(m["dew"]) if m["dew"] else None
        elif m := re.fullmatch(r"Q(\d{4})", token):
            fields["qnh_hpa"] = int(m[1])
        elif m := re.fullmatch(r"A(\d{4})", token):
            fields["qnh_hpa"] = round(int(m[1]) / 100 * HPA_PER_INHG)
        elif PHENOMENON.fullmatch(token):
            weather.append(token)

    return Metar(raw=raw.strip(), station=station, time=time, clouds=tuple(clouds), weather=tuple(weather), **fields)


def _celsius(text: str) -> int:
    return -int(text[1:]) if text.startswith("M") else int(text)
