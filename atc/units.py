"""Frequencies are integer kHz everywhere inside the app; floats only exist at the edges (sim, user input)."""

COM_MIN_KHZ = 118000
COM_MAX_KHZ = 136990


def mhz_to_khz(mhz: float) -> int:
    # The sim reports 126.855 as 126.85499999999999, so never compare MHz floats directly
    return round(mhz * 1000)


def parse_mhz(text: str) -> int:
    """Parse a COM frequency typed by the user, e.g. '121.28' or '121,280'."""
    try:
        khz = mhz_to_khz(float(text.strip().replace(",", ".")))
    except ValueError:
        raise ValueError(f"not a frequency: {text!r}") from None
    if not COM_MIN_KHZ <= khz <= COM_MAX_KHZ:
        raise ValueError(f"{text} is outside the VHF COM band (118.000-136.990)")
    return khz


def format_khz(khz: int) -> str:
    return f"{khz // 1000}.{khz % 1000:03}"


def parse_level(text: str) -> int:
    """'FL240' -> 24000 ft, '5000' -> 5000 ft."""
    t = text.strip().upper()
    if t.startswith("FL"):
        return int(t[2:]) * 100
    return int(t)
