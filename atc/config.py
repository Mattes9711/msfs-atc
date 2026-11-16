"""User settings: settings.toml in the user's app-data folder (see atc/paths.py), or a file given with --config.
A missing settings file just means defaults. Unknown keys are an error, so typos don't fail silently.
API keys, if ever needed, belong in the settings file, never in the code."""
import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

from atc import paths

ROOT = paths.resources()  # read-only files that ship with the app (data/, atc/app/static)


class ConfigError(Exception):
    pass


@dataclass
class WhisperConfig:
    model: str = "small.en"
    device: str = "cpu"
    beam_size: int = 5
    mic: int | None = None
    ptt_key: str = "right ctrl"  # a name, "key:0xA3" or "joy:0:5" (atc/audio/ptt.py); the Settings page sets it
    ptt_key2: str | None = None  # a spare binding, e.g. a yoke button next to the keyboard key
    save_recordings: bool = False  # keep every transmission in recordings/ (to check misheard calls later)


@dataclass
class AtcConfig:
    strict_readback: bool = True  # every instruction read back before switching frequency or going on


@dataclass
class TrafficConfig:
    chatter: bool = True  # the other aircraft's radio calls (LiveTraffic, FSLTL, MSFS) on your frequency
    start_livetraffic: bool = False  # start LiveTraffic with the app (off by default since 2026-11-16, user wish)
    livetraffic_exe: Path = Path()  # empty = from MSFS's EXE.xml, where LiveTraffic puts itself


@dataclass
class CabinConfig:
    announcements: bool = True  # the purser's announcements, in the airline's language and English (C1)


@dataclass
class MixerConfig:
    """Loudness in percent of each kind of voice (the sound mixer, 2026-11-16); changes apply at once."""
    master: int = 100
    atc: int = 100  # the controllers and the ATIS
    traffic: int = 80  # the other aircraft and their controllers on your frequency
    copilot: int = 100
    cabin: int = 50  # the purser's announcements and the chime (70 was too loud next to ATC: Milestone 8, F1)


@dataclass
class GsxConfig:
    read: bool = True  # follow GSX Pro: boarding done -> doors closed announcement, pushback started (C3)
    control: bool = True  # request the GSX pushback after ATC's approval and deboarding at the stand (C4)


@dataclass
class TtsConfig:
    engine: str = "piper"  # "piper" (a voice per controller) or "sapi" (the Windows voice)
    voice: str = "Zira"  # the Windows voice, also the fallback when Piper can't start
    rate: int | None = None  # words per minute; default about 170 (Piper) / 200 (Windows)
    radio_effect: bool = True  # Piper only: sounds like VHF radio (narrow band, hiss, squelch)


@dataclass
class Config:
    # JSON airports: written by `python -m atc.airport.export`. The ones in data/airports are test data from the
    # developer's Little Navmap database and must not be shipped (see BUILD.md, data licences).
    airports_dir: Path = ROOT / "data" / "airports"
    centers_file: Path = ROOT / "data" / "centers.json"  # corrections to the Center sectors; missing file = none
    # Shipped: German Center sectors from VATSIM data (CC BY-SA 4.0, atc/airspace/vatsim.py), used without Little
    # Navmap's
    vatsim_centers_file: Path = ROOT / "data" / "centers_vatsim.json"
    # LICENCE: the user's own Little Navmap database, built from the scenery they installed (payware add-ons
    # included). It is only read on the user's machine; never ship it or data exported from it.
    # Empty = found by itself: the database of the MSFS that runs, 2020 or 2024 (atc/airport/lnm_files.py)
    littlenavmap_db: Path = Path()
    simbrief_username: str | None = None
    # SimConnect.dll: empty = look for it (next to the app, MSFS SDK, ...), see atc/sim/native.py find_dll
    simconnect_dll: Path = Path()
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    tts: TtsConfig = field(default_factory=TtsConfig)
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    cabin: CabinConfig = field(default_factory=CabinConfig)
    gsx: GsxConfig = field(default_factory=GsxConfig)
    mixer: MixerConfig = field(default_factory=MixerConfig)
    atc: AtcConfig = field(default_factory=AtcConfig)


def load_config(path: Path | None = None) -> Config:
    """Load the settings; without an explicit path a missing settings.toml just means defaults."""
    if path is None:
        path = paths.settings_file()
        if not path.exists():
            return Config()
    elif not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)
    return _build(Config, data, path.parent, section="")


def _build(cls, data: dict, base_dir: Path, section: str):
    defaults = cls()
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        # Catches typos like "whsiper" instead of silently ignoring them
        raise ConfigError(f"unknown config key(s) in [{section or 'root'}]: {', '.join(sorted(unknown))}")
    kwargs = {}
    for name, value in data.items():
        default = getattr(defaults, name)
        if is_dataclass(default):
            kwargs[name] = _build(type(default), value, base_dir, section=name)
        elif isinstance(default, Path):
            kwargs[name] = base_dir / value
        else:
            kwargs[name] = value
    return cls(**kwargs)
