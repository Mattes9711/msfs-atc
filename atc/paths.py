"""Where things are (Milestone 3c, D1).

Two kinds of files:
- Resources ship with the app and are only read: the page (atc/app/static), data/centers.json.
  Next to the code while developing; inside the PyInstaller build later (sys._MEIPASS).
- Everything the app writes goes to the user's folders, because an installed app under C:\\Program Files may
  not write into its own folder:
    %APPDATA%\\MSFS ATC\\settings.toml        user settings (roams with the Windows account)
    %LOCALAPPDATA%\\MSFS ATC\\cache\\...       METAR, SimBrief, ...
    %LOCALAPPDATA%\\MSFS ATC\\models          the whisper model, downloaded on first start
    %LOCALAPPDATA%\\MSFS ATC\\logs, recordings, window.json

MSFS_ATC_HOME points both user folders somewhere else (tests, a portable copy).
The folders are looked up on every call, so tests can redirect them.
"""
import os
import sys
from pathlib import Path

APP_NAME = "MSFS ATC"


def resources() -> Path:
    """Where the read-only files are: the project folder, or the unpacked PyInstaller build."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _user_dir(env_var: str, fallback: str) -> Path:
    if home := os.environ.get("MSFS_ATC_HOME"):
        return Path(home)
    base = os.environ.get(env_var)
    return (Path(base) if base else Path.home() / fallback) / APP_NAME


def config_dir() -> Path:
    """User settings (%APPDATA%\\MSFS ATC)."""
    return _user_dir("APPDATA", "AppData/Roaming")


def data_dir() -> Path:
    """Everything else the app writes (%LOCALAPPDATA%\\MSFS ATC)."""
    return _user_dir("LOCALAPPDATA", "AppData/Local")


def settings_file() -> Path:
    return config_dir() / "settings.toml"


def cache_dir(name: str) -> Path:
    return data_dir() / "cache" / name


def models_dir() -> Path:
    return data_dir() / "models"


def recordings_dir() -> Path:
    return data_dir() / "recordings"


def logs_dir() -> Path:
    return data_dir() / "logs"
