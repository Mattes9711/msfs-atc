"""Remembering the window's size and position between starts (Milestone 3c, D2).

Saved as JSON in the user's data folder. Before using a saved position it is checked against the screens that
are connected now: a window last seen on an unplugged second monitor would otherwise open off-screen."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_SIZE = (1100, 760)  # fits next to MSFS on one screen, or full on a second monitor
MIN_SIZE = (420, 400)  # small window next to the sim: the layout still works (mobile breakpoint is 720 px)
MIN_VISIBLE = 80  # at least this much of the window must be on a screen, so it can still be grabbed


@dataclass(frozen=True)
class Geometry:
    x: int
    y: int
    width: int
    height: int
    maximized: bool = False


def load(path: Path) -> Geometry | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Geometry(int(data["x"]), int(data["y"]), max(MIN_SIZE[0], int(data["width"])),
                        max(MIN_SIZE[1], int(data["height"])), bool(data.get("maximized", False)))
    except (OSError, ValueError, KeyError, TypeError):
        return None  # first start, or a broken file: use the default


def save(path: Path, geometry: Geometry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(geometry)), encoding="utf-8")


def on_screen(g: Geometry, screens) -> bool:
    """True if a grabbable part of the window (MIN_VISIBLE in both directions) is on one of the screens.
    `screens` have x, y, width, height (pywebview's webview.screens)."""
    for s in screens:
        overlap_x = min(g.x + g.width, s.x + s.width) - max(g.x, s.x)
        overlap_y = min(g.y + g.height, s.y + s.height) - max(g.y, s.y)
        if overlap_x >= MIN_VISIBLE and overlap_y >= MIN_VISIBLE and s.y <= g.y < s.y + s.height:
            return True  # the title bar (top edge) is on this screen, so the window can be moved
    return False


def initial(saved: Geometry | None, screens) -> Geometry | None:
    """The geometry to open with, or None for the default size, centred by the system."""
    if saved is None or (screens and not on_screen(saved, screens)):
        return None
    return saved
