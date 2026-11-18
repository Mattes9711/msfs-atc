"""python -m atc.app: the desktop app (Milestone 3c, D2).

The backend (local server, and with it the session: SimConnect, speech, ATC) starts first, then a pywebview window
shows the page. pywebview draws it with Microsoft's WebView2, which Windows 10/11 already has. Closing the window
ends everything: the session stops, SimConnect closes, the server shuts down, and the process exits.

  --browser    open the normal browser instead (debugging); Ctrl+C ends
  --no-window  only print the address (development, tests)
"""
import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from atc import paths
from atc.app import window_state
from atc.app.overlay import SIZE as OVERLAY_SIZE, Overlay
from atc.app.server import App, make_server
from atc.config import ConfigError, load_config
from atc.sim import livetraffic

DEFAULT_PORT = 8350
TITLE = "MSFS ATC"
BACKGROUND = "#0b0d14"  # the page's background: no white flash while the window loads


def window_state_file() -> Path:
    return paths.data_dir() / "window.json"


def overlay_file() -> Path:
    return paths.data_dir() / "overlay.json"


def bind(app: App, port: int):
    """The usual port, or any free one if it is taken (e.g. a second copy is running)."""
    try:
        return make_server(app, port)
    except OSError:
        return make_server(app, 0)


def log_to_file_without_console() -> None:
    """Started with pythonw (start.bat, later the .exe) there is no console: keep messages in a log file."""
    if sys.stdout is None or sys.stderr is None:
        paths.logs_dir().mkdir(parents=True, exist_ok=True)
        log = open(paths.logs_dir() / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


class GeometryTracker:
    """Follows the window's moves and resizes, so the last normal (not minimised, not maximised) size and position
    can be saved when it closes."""

    def __init__(self, start: window_state.Geometry | None):
        self.geometry = start
        self.minimized = False
        self.maximized = bool(start and start.maximized)

    def attach(self, window) -> None:
        events = window.events
        events.minimized += lambda: setattr(self, "minimized", True)
        events.maximized += lambda: setattr(self, "maximized", True)
        events.restored += self._restored
        events.moved += lambda x, y: self._update(window)
        events.resized += lambda width, height: self._update(window)

    def _restored(self) -> None:
        self.minimized = self.maximized = False

    def _update(self, window) -> None:
        if self.minimized or self.maximized:
            return  # minimised windows sit at -32000; maximised size is not the size to restore
        self.geometry = window_state.Geometry(window.x, window.y, window.width, window.height)

    def result(self) -> window_state.Geometry | None:
        if self.geometry is None:
            return None
        g = self.geometry
        return window_state.Geometry(g.x, g.y, g.width, g.height, self.maximized)


def run_window(url: str, app: App | None = None) -> bool:
    """Show the app in its own window until it is closed. False if that isn't possible (then use a browser).
    With the app given, also the overlay over the sim (hidden until a flight starts)."""
    try:
        import webview
    except ImportError:
        print("pywebview is not installed (pip install -r requirements.txt)")
        return False
    saved = window_state.initial(window_state.load(window_state_file()), webview.screens)
    size = (saved.width, saved.height) if saved else window_state.DEFAULT_SIZE
    window = webview.create_window(TITLE, url, width=size[0], height=size[1], x=saved and saved.x,
                                   y=saved and saved.y, maximized=bool(saved and saved.maximized),
                                   min_size=window_state.MIN_SIZE, background_color=BACKGROUND)
    tracker = GeometryTracker(saved)
    tracker.attach(window)
    overlay = None
    if app is not None:
        overlay = Overlay.load(overlay_file(), webview.screens)
        small = webview.create_window(f"{TITLE} overlay", url + "overlay", width=OVERLAY_SIZE[0],
                                      height=OVERLAY_SIZE[1], x=overlay.x, y=overlay.y, resizable=False,
                                      frameless=True, easy_drag=False, on_top=True, hidden=True, focus=False,
                                      background_color=BACKGROUND)
        overlay.attach(small)
        window.events.closed += small.destroy  # the app ends only when every window is closed
        app.overlay = overlay
    try:
        webview.start()  # blocks until the window is closed
    except Exception as e:  # e.g. no WebView2 runtime
        print(f"could not open the app window ({e}); the WebView2 runtime may be missing: "
              "https://developer.microsoft.com/microsoft-edge/webview2/")
        return False
    if geometry := tracker.result():
        window_state.save(window_state_file(), geometry)
    if overlay is not None:
        app.overlay = None
        overlay.save()
    return True


def wait_for_ctrl_c() -> None:
    print("Press Ctrl+C to stop.")
    threading.Event().wait()


def main(argv: list[str] | None = None) -> None:
    log_to_file_without_console()
    p = argparse.ArgumentParser(prog="python -m atc.app", description="MSFS ATC desktop app")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--config", type=Path,
                   help="settings file (default: settings.toml in %%APPDATA%%\\MSFS ATC, if present)")
    p.add_argument("--browser", action="store_true", help="open the normal browser instead of the app window")
    p.add_argument("--no-window", action="store_true", help="don't open anything, just print the address")
    args = p.parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as e:
        p.error(str(e))
    app = App(config, settings_path=args.config)
    print(livetraffic.start(config))
    server = bind(app, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"MSFS ATC backend running at {url}")
    try:
        if args.no_window:
            wait_for_ctrl_c()
        elif args.browser or not run_window(url, app):
            webbrowser.open(url)
            wait_for_ctrl_c()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown(app, server)


def shutdown(app: App, server) -> None:
    """Stop the session (closes SimConnect, input and voice threads) and the server, in that order."""
    app.stop()
    server.shutdown()
    server.server_close()
    print("MSFS ATC stopped.")


if __name__ == "__main__":
    main()
