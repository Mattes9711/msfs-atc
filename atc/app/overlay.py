"""The overlay: a small window over the sim with what matters right now (2026-11-18).

COM and the next frequency, the last call from ATC, cleared altitude, squawk and QNH, what to say next, and the
words while push-to-talk is held. Frameless and always on top; it shows only during a flight, and only over MSFS
in windowed or borderless mode (exclusive fullscreen and VR draw over every window).

Its position and whether it is wanted are remembered in overlay.json, next to window.json.
"""
import json
from pathlib import Path

from atc.app import window_state

SIZE = (340, 232)
MARGIN = 24  # from the screen's right edge, first start
TOP = 96  # from the screen's top, first start: below the sim's own toolbar


class Overlay:
    """The pywebview window behind App.overlay: wanted (the user's choice), show() and hide()."""

    def __init__(self, path: Path, x: int | None = None, y: int | None = None, wanted: bool = True):
        self.path, self.x, self.y, self._wanted = path, x, y, wanted
        self.window = None

    @classmethod
    def load(cls, path: Path, screens) -> "Overlay":
        """The saved place if it is still on a screen, else the top right of the first screen."""
        x = y = None
        wanted = True
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            wanted = bool(data.get("visible", True))
            x, y = int(data["x"]), int(data["y"])
            if screens and not window_state.on_screen(window_state.Geometry(x, y, *SIZE), screens):
                x = y = None
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if x is None and screens:
            s = screens[0]
            x, y = s.x + s.width - SIZE[0] - MARGIN, s.y + TOP
        return cls(path, x, y, wanted)

    @property
    def wanted(self) -> bool:
        return self._wanted

    @wanted.setter
    def wanted(self, value: bool) -> None:
        self._wanted = value
        self.save()

    def attach(self, window) -> None:
        self.window = window
        window.events.moved += self._moved

    def _moved(self, x: int, y: int) -> None:
        self.x, self.y = x, y

    def show(self) -> None:
        if self.window is not None:
            self.window.show()

    def hide(self) -> None:
        if self.window is not None:
            self.window.hide()

    def save(self) -> None:
        data = {"visible": self._wanted}
        if self.x is not None and self.y is not None:
            data |= {"x": self.x, "y": self.y}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass  # not remembered, the overlay still works
