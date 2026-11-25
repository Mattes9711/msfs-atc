"""C3/C4: GSX Pro read through its L-vars and controlled through its menu, against a fake GSX."""
import struct
from types import SimpleNamespace

from atc.events import Collector
from atc.gsx_link import GsxLink
from atc.sim import gsx
from atc.sim.native import NativeSimConnect, Var
from atc.sim.simconnect import GSX_TRIES, SimConnectSource

MAIN = ["Ground services at gate A12", "Request Deboarding", "Request Catering", "Request Boarding",
        "Request Pushback"]


def lvars(running=1, boarding=gsx.AVAILABLE, deboarding=gsx.NOT_AVAILABLE, departure=gsx.AVAILABLE):
    return {gsx.STATE_LVARS["running"]: running, gsx.STATE_LVARS["boarding"]: boarding,
            gsx.STATE_LVARS["deboarding"]: deboarding, gsx.STATE_LVARS["departure"]: departure}


class FakeGsx:
    """Writes its menu file like GSX does when the L-vars are set."""

    def __init__(self, path, after_choice=None):
        self.path, self.after_choice, self.set = path, after_choice, []
        self.time = [100.0]

    def set_lvar(self, name, value):
        self.set.append((name, value))
        self.time[0] += 1
        if name == gsx.MENU_OPEN:
            self._write(MAIN)
        elif name == gsx.MENU_CHOICE and self.after_choice:
            self._write(self.after_choice)

    def _write(self, lines):
        import os

        self.path.write_text("\n".join(lines), encoding="utf-8")
        os.utime(self.path, (self.time[0], self.time[0]))

    def menu(self):
        clock = [0.0]
        return gsx.GsxMenu(self.set_lvar, self.path, clock=lambda: clock[0],
                           sleep=lambda s: clock.__setitem__(0, clock[0] + s))


def test_the_state_from_its_lvars():
    assert gsx.state_from_lvars(lvars(running=0)) is None and gsx.state_from_lvars(None) is None
    state = gsx.state_from_lvars(lvars(boarding=gsx.COMPLETED, departure=gsx.PERFORMING))
    assert state.boarding_done and state.pushing


def test_the_menu_picks_the_pushback(tmp_path):
    fake = FakeGsx(tmp_path / "menu")
    assert fake.menu().request("pushback") == "GSX: pushback requested (Request Pushback)"
    assert fake.set == [(gsx.MENU_OPEN, 1), (gsx.MENU_CHOICE, 3)]  # the fourth option line


def test_a_follow_up_question_is_left_to_the_pilot(tmp_path):
    fake = FakeGsx(tmp_path / "menu", after_choice=["Select pushback direction", "Nose left", "Nose right"])
    line = fake.menu().request("pushback")
    assert "GSX asks \"Select pushback direction\"" in line
    assert fake.set == [(gsx.MENU_OPEN, 1), (gsx.MENU_CHOICE, 3)]  # nothing picked for the pilot


def test_no_such_service_closes_the_menu_and_says_so(tmp_path):
    fake = FakeGsx(tmp_path / "menu")
    MAIN_WITHOUT = [line for line in MAIN if "Deboarding" not in line]
    fake._write = lambda lines, w=fake._write: w(MAIN_WITHOUT)
    assert fake.menu().request("deboarding").startswith("GSX: no deboarding in its menu")
    assert fake.set[-1] == (gsx.MENU_CHOICE, -2)


def test_a_menu_that_never_opens(tmp_path):
    clock = [0.0]
    menu = gsx.GsxMenu(lambda n, v: None, tmp_path / "menu", clock=lambda: clock[0],
                       sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    assert menu.request("pushback").startswith("GSX: its menu did not open")


def test_a_menu_that_opens_on_the_second_try(tmp_path):
    """Milestone 8, E1: twice in the test flight "its menu did not open". Now it waits 10 s, and opens it again."""
    fake = FakeGsx(tmp_path / "menu")
    opened = []
    real = fake.set_lvar

    def slow(name, value):
        if name == gsx.MENU_OPEN and not opened:
            opened.append(True)
            fake.set.append((name, value))  # the first click is lost
            return
        real(name, value)

    fake.set_lvar = slow
    menu = fake.menu()
    menu.set_lvar = slow
    assert menu.request("pushback") == "GSX: pushback requested (Request Pushback)"
    assert fake.set == [(gsx.MENU_OPEN, 1), (gsx.MENU_OPEN, 1), (gsx.MENU_CHOICE, 3)]


def test_a_menu_that_never_opens_is_closed_and_its_file_logged(tmp_path):
    (tmp_path / "menu").write_text("Loading...", encoding="utf-8")
    clock, set_ = [0.0], []
    menu = gsx.GsxMenu(lambda n, v: set_.append((n, v)), tmp_path / "menu", clock=lambda: clock[0],
                       sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    result = menu.request("pushback")
    assert "tried 2 times" in result and result.endswith("said: Loading...)")
    assert set_ == [(gsx.MENU_OPEN, 1), (gsx.MENU_OPEN, 1), (gsx.MENU_CHOICE, -2)]
    assert 20 <= clock[0] < 21  # 10 s each


def test_the_menu_is_stepped_without_waiting(tmp_path):
    """The live loop polls it: no call blocks."""
    fake = FakeGsx(tmp_path / "menu")
    clock = [0.0]
    menu = gsx.GsxMenu(fake.set_lvar, fake.path, clock=lambda: clock[0], sleep=lambda s: 1 / 0)
    menu.start("pushback")
    assert menu.busy and fake.set == [(gsx.MENU_OPEN, 1)]
    assert menu.poll() is None and fake.set[-1] == (gsx.MENU_CHOICE, 3)  # the menu was there: chosen
    assert menu.poll() is None  # a follow-up question could still come
    clock[0] = 4
    assert menu.poll() == "GSX: pushback requested (Request Pushback)" and not menu.busy


class Sim:
    def __init__(self, values):
        self.values = values

    def gsx_values(self):
        return self.values

    def set_lvar(self, name, value):
        pass


class Menu:
    """Done one poll after the start."""

    def __init__(self):
        self.asked, self.service = [], None

    @property
    def busy(self):
        return self.service is not None

    def start(self, service):
        self.asked.append(service)
        self.service = service

    def poll(self):
        service, self.service = self.service, None
        return f"GSX: {service} requested" if service else None


def link(values, control=True):
    clock, menu = [0.0], Menu()
    return GsxLink(Sim(values), control, clock=lambda: clock[0], menu=menu), menu, clock


def test_pushback_requested_once_after_the_approval_is_read_back():
    gsx_link, menu, clock = link(lvars())
    atc = SimpleNamespace(phase="pushback", pending=("pushback",), stand_in=None)
    sink = Collector()
    gsx_link.step(atc, None, sink)
    assert menu.asked == []  # the readback first
    atc.pending, clock[0] = (), 10
    gsx_link.step(atc, None, sink)
    clock[0] = 20
    gsx_link.step(atc, None, sink)
    assert menu.asked == ["pushback"] and sink.events[-1].text == "GSX: pushback requested"


def test_a_pushback_the_pilot_ordered_himself_is_left_alone():
    gsx_link, menu, _ = link(lvars(departure=gsx.REQUESTED))
    gsx_link.step(SimpleNamespace(phase="pushback", pending=(), stand_in=None), None, Collector())
    assert menu.asked == []


def parked(**kw):
    return SimpleNamespace(**{"lat": 48.35, "lon": 11.78, "ground_speed_kt": 0, "engines_running": False,
                              "parking_brake": True, **kw})


def arrived(stand_in, *stands):
    return SimpleNamespace(phase="taxi_in", pending=(), stand_in=stand_in,
                           destination=SimpleNamespace(parking=stands))


def test_deboarding_at_the_stand_after_the_flight():
    stand = SimpleNamespace(lat=48.35, lon=11.78)
    gsx_link, menu, _ = link(lvars(deboarding=gsx.AVAILABLE))
    gsx_link.step(arrived(stand, stand), parked(), Collector())
    assert menu.asked == ["deboarding"]


def test_deboarding_at_another_stand_than_ground_gave():
    """Milestone 8, E2: parked at another stand, GSX never deboarded."""
    gsx_link, menu, _ = link(lvars(deboarding=gsx.AVAILABLE))
    given, other = SimpleNamespace(lat=48.36, lon=11.79), SimpleNamespace(lat=48.35, lon=11.78)
    gsx_link.step(arrived(given, given, other), parked(), Collector())
    assert menu.asked == ["deboarding"]


def test_no_deboarding_before_the_engines_are_off_and_the_brake_set():
    stand = SimpleNamespace(lat=48.35, lon=11.78)
    for aircraft in (parked(engines_running=True), parked(parking_brake=False)):
        gsx_link, menu, _ = link(lvars(deboarding=gsx.AVAILABLE))
        gsx_link.step(arrived(stand, stand), aircraft, Collector())
        assert menu.asked == []


def test_without_control_only_reading_and_notes():
    gsx_link, menu, clock = link(lvars(), control=False)
    atc = SimpleNamespace(phase="pushback", pending=(), stand_in=None)
    sink = Collector()
    gsx_link.step(atc, None, sink)
    gsx_link.sim.values = lvars(boarding=gsx.COMPLETED, departure=gsx.PERFORMING)
    clock[0] = 10
    assert gsx_link.step(atc, None, sink).boarding_done
    assert [e.text for e in sink.events] == ["GSX: boarding completed", "GSX: pushback started"]
    assert menu.asked == []


def test_the_doors_wait_for_gsx_boarding():
    from atc.cabin import Cabin
    from atc.runtime import announce

    cabin = Cabin.for_flight("DLH241", "Munich")
    cabin.said.add("boarding")
    state = SimpleNamespace(on_ground=True, alt_msl_ft=50)
    atc = SimpleNamespace(phase="pushback", descent_given=False)
    sink = Collector()
    announce(cabin, atc, state, sink, gsx.state_from_lvars(lvars()), with_gsx=True)
    assert sink.events == []
    announce(cabin, atc, state, sink, gsx.state_from_lvars(lvars(boarding=gsx.COMPLETED)), with_gsx=True)
    assert sink.events[0].text.startswith("Meine Damen und Herren, die Türen sind geschlossen")


def test_lvars_keep_their_names_and_are_written_as_doubles():
    assert Var(gsx.MENU_OPEN, "number").simvar == "L:FSDT_GSX_MENU_OPEN"

    class Dll:
        def __init__(self):
            self.added, self.written = [], []

        def add(self, define, name, units, kind):
            self.added.append((define, name))

        def set_data(self, define, data):
            self.written.append((define, data))

    dll = Dll()
    native = NativeSimConnect(dll, {"gsx_menu_open": (Var(gsx.MENU_OPEN, "number"),)})
    native.set(gsx.MENU_OPEN, 1)
    assert dll.added == [(1, "L:FSDT_GSX_MENU_OPEN")] and dll.written == [(1, struct.pack("<d", 1.0))]


def test_reading_gives_up_when_the_sim_never_answers():
    class Requests:
        calls = 0

        def get(self, name):
            Requests.calls += 1
            return None

    sim = SimConnectSource(Requests())
    for _ in range(GSX_TRIES + 3):
        assert sim.gsx_values() is None
    assert Requests.calls == GSX_TRIES * len(gsx.STATE_LVARS)


def test_an_old_menu_file_is_not_read_as_the_new_one(tmp_path):
    fake = FakeGsx(tmp_path / "menu")
    fake._write(["Old menu", "Request Pushback"])  # left from earlier
    fake.time[0] += 5
    assert fake.menu().request("pushback") == "GSX: pushback requested (Request Pushback)"
    assert fake.set[-1] == (gsx.MENU_CHOICE, 3)  # chosen from the new menu, not the old one's 0


def test_the_menu_file_is_found_in_the_gsx_pro_package(tmp_path):
    """2026-11-25: GSX Pro on MSFS writes its menu into its panel's folder, not %APPDATA%\\Virtuali\\GSX."""
    root, packages = tmp_path / "Addon Manager", tmp_path / "XboxGames"
    env = {"APPDATA": str(tmp_path / "Roaming")}
    places = gsx.menu_candidates(str(root), packages, env)
    assert places[0] == root / "MSFS" / "fsdreamteam-gsx-pro" / "html_ui" / "InGamePanels" / "FSDT_GSX_Panel" / "menu"
    assert places[1] == packages / "Community" / "fsdreamteam-gsx-pro" / gsx.PANEL
    assert gsx.menu_file(places) == places[-1]  # none there yet: the old place, so the log names one
    places[1].parent.mkdir(parents=True)
    places[1].write_text("", encoding="utf-8")
    assert gsx.menu_file(places) == places[1]


def test_the_community_folder_from_usercfg(tmp_path):
    cfg = tmp_path / "Packages" / "Microsoft.FlightSimulator_8wekyb3d8bbwe" / "LocalCache" / "UserCfg.opt"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('Version 1\nInstalledPackagesPath "D:\\XboxGames"\n', encoding="utf-8")
    assert str(gsx._packages_path({"LOCALAPPDATA": str(tmp_path), "APPDATA": str(tmp_path / "none")})) == "D:\\XboxGames"
    assert gsx._packages_path({"LOCALAPPDATA": str(tmp_path / "none"), "APPDATA": str(tmp_path / "none")}) is None


def test_a_boot_message_is_not_a_menu(tmp_path):
    """GSX's auto-restarter writes "#BOOT# ..." into the menu file while GSX restarts."""
    clock = [0.0]
    menu = gsx.GsxMenu(lambda n, v: (tmp_path / "menu").write_text("#BOOT# GSX restarting\nplease wait",
                                                                   encoding="utf-8"),
                       tmp_path / "menu", clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    assert "did not open" in menu.request("pushback")


def test_a_skipped_request_says_why_once():
    gsx_link, menu, clock = link(lvars(departure=gsx.NOT_AVAILABLE))
    atc, sink = SimpleNamespace(phase="pushback", pending=(), stand_in=None), Collector()
    gsx_link.step(atc, None, sink)
    clock[0] = 10
    gsx_link.step(atc, None, sink)
    assert menu.asked == [] and [e.text for e in sink.events] == [
        "GSX: pushback not requested yet, GSX has it not available"]
    gsx_link.sim.values, clock[0] = lvars(departure=gsx.AVAILABLE), 20  # GSX offers it later: asked then
    gsx_link.step(atc, None, sink)
    assert menu.asked == ["pushback"]
