"""The settings the app's Settings page edits (Milestone 5, R4): what they are, checking new values, writing them.

settings.toml stays the one place for settings (atc/config.py reads it). The page sends flat names like
"tts.engine"; apply() checks every value and returns a new Config, save() writes only what differs from the
defaults, so a later default change still reaches users who never touched that setting.
"""
import json
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

from atc.audio.ptt import parse as parse_binding
from atc.config import Config, ConfigError

TTS_ENGINES = ("piper", "sapi")  # same as atc/audio/setup.py (not imported: that would load the audio stack)

# "section.key" → (kind, extra). Kinds: text, path, bool, choice (extra = the choices), int (extra = (min, max)),
# all but bool may be empty = the default.
EDITABLE = {
    "simbrief_username": ("text", None),
    "simconnect_dll": ("path", None),
    "littlenavmap_db": ("path", None),
    "tts.engine": ("choice", TTS_ENGINES),
    "tts.voice": ("text", None),
    "tts.rate": ("int", (80, 300)),
    "tts.radio_effect": ("bool", None),
    "whisper.mic": ("int", (0, 999)),
    "whisper.ptt_key": ("binding", None),
    "whisper.ptt_key2": ("binding", None),
    "whisper.live_text": ("bool", None),
    "traffic.chatter": ("bool", None),
    "cabin.announcements": ("bool", None),
    "gsx.read": ("bool", None),
    "gsx.control": ("bool", None),
    "traffic.start_livetraffic": ("bool", None),
    "traffic.livetraffic_exe": ("path", None),
    "atc.strict_readback": ("bool", None),
    "mixer.master": ("int", (0, 100)),
    "mixer.atc": ("int", (0, 100)),
    "mixer.traffic": ("int", (0, 100)),
    "mixer.copilot": ("int", (0, 100)),
    "mixer.cabin": ("int", (0, 100)),
}


def _get(config: Config, name: str):
    obj = config
    for part in name.split("."):
        obj = getattr(obj, part)
    return obj


def _set(config: Config, name: str, value) -> Config:
    if "." not in name:
        return replace(config, **{name: value})
    section, key = name.split(".")
    return replace(config, **{section: replace(getattr(config, section), **{key: value})})


def view(config: Config) -> dict:
    """The page's values: paths as text, an empty path as ""."""
    out = {}
    for name, (kind, _) in EDITABLE.items():
        value = _get(config, name)
        out[name] = ("" if value == Path() else str(value)) if kind == "path" else value
    return out


def apply(config: Config, values: dict) -> Config:
    """A new Config with the page's values. A wrong value is a ConfigError naming the setting."""
    defaults = Config()
    for name, value in values.items():
        if name not in EDITABLE:
            raise ConfigError(f"unknown setting {name!r}")
        kind, extra = EDITABLE[name]
        if kind == "bool":
            if not isinstance(value, bool):
                raise ConfigError(f"{name}: on or off")
        elif value in ("", None):
            value = _get(defaults, name)  # empty = the default
        elif kind == "text":
            value = str(value).strip()
        elif kind == "path":
            value = Path(str(value).strip())
        elif kind == "binding":
            try:
                value = parse_binding(str(value)).text if str(value).startswith(("key:", "joy:")) else \
                    str(value).strip().lower()
                parse_binding(value)
            except ValueError:
                raise ConfigError(f"{name}: press the key or button again in the Settings page") from None
        elif kind == "choice":
            if value not in extra:
                raise ConfigError(f"{name}: one of {', '.join(extra)}")
        elif kind == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ConfigError(f"{name}: a whole number") from None
            if not extra[0] <= value <= extra[1]:
                raise ConfigError(f"{name}: between {extra[0]} and {extra[1]}")
        config = _set(config, name, value)
    return config


def _toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Path):
        value = value.as_posix()
    return json.dumps(str(value))  # a TOML basic string is written like a JSON string


def save(config: Config, path: Path) -> None:
    """Write every setting that differs from the defaults; sections as [whisper], [tts], [traffic]."""
    defaults = Config()
    root, sections = [], []
    for f in fields(config):
        value, default = getattr(config, f.name), getattr(defaults, f.name)
        if is_dataclass(value):
            lines = [f"{g.name} = {_toml(getattr(value, g.name))}" for g in fields(value)
                     if getattr(value, g.name) != getattr(default, g.name) and getattr(value, g.name) is not None]
            if lines:
                sections.append(f"\n[{f.name}]\n" + "\n".join(lines) + "\n")
        elif value != default and value is not None:
            root.append(f"{f.name} = {_toml(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# MSFS ATC settings, written by the app's Settings page. Missing keys use the defaults.\n"
                    + "\n".join(root) + ("\n" if root else "") + "".join(sections), encoding="utf-8")
