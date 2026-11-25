"""Check the MSFS connection by itself: python -m atc.sim.check

Connects through our own SimConnect client, reads the aircraft state and the weather a few times and lists the other
aircraft around (LiveTraffic, FSLTL or MSFS AI) with their model titles, with how long each read took. For testing
with MSFS running (steps S1, S2, L1).
"""
import argparse
import time

from atc.config import load_config
from atc.sim.simconnect import SimConnectSource, SimUnavailable


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m atc.sim.check", description=__doc__.splitlines()[0])
    p.add_argument("--reads", type=int, default=3, help="how many times to read the state")
    p.add_argument("--tune", type=float, metavar="MHZ", help="also set COM1, as the co-pilot does (C2), e.g. 121.705")
    p.add_argument("--gsx-menu", action="store_true", help="also open the GSX menu and print it (C4)")
    args = p.parse_args(argv)
    try:
        sim = SimConnectSource(dll_path=load_config().simconnect_dll)
    except SimUnavailable as e:
        print(e)
        return 1
    try:
        for _ in range(args.reads):
            start = time.perf_counter()
            try:
                s = sim.read()
            except SimUnavailable as e:
                print(e)
                return 1
            print(f"{time.perf_counter() - start:5.2f} s  {s.lat:.5f} {s.lon:.5f}  {s.alt_msl_ft:.0f} ft "
                  f"(AGL {s.alt_agl_ft:.0f})  HDG {s.heading_mag:03.0f}  GS {s.ground_speed_kt:.0f} kt  "
                  f"{'on ground' if s.on_ground else 'airborne'}  COM1 {s.com1_khz / 1000:.3f}  "
                  f"wind {s.wind_dir_true:03.0f}/{s.wind_speed_kt:.0f}" + ("  (stale)" if sim.stale else ""))
            time.sleep(1)
        if w := sim.weather():
            print(f"weather: {w.temp_c:.0f} °C, {w.sea_level_hpa:.0f} hPa, visibility {w.visibility_m:.0f} m")
        start = time.perf_counter()
        traffic = sim.traffic()
        print(f"{time.perf_counter() - start:5.2f} s  {len(traffic)} other aircraft within 40 nm")
        print(traffic_summary(traffic))
        for t in sorted(traffic, key=lambda t: (not t.on_ground, -t.ground_speed_kt))[:40]:
            print(f"       {t.callsign:<20} {t.model:<10} {t.alt_ft:6.0f} ft  {t.ground_speed_kt:4.0f} kt  "
                  f"{'ground' if t.on_ground else 'air   '}  {t.title[:45]}")
        check_gsx(sim, args.gsx_menu)
        if args.tune:
            check_tuning(sim, args.tune)
        return 0
    finally:
        sim.close()


def check_gsx(sim: SimConnectSource, open_menu: bool) -> None:
    """GSX's L-vars as SimConnect reads them (C3): do they come at all (MSFS 2020 since SU12), and what values."""
    from atc.sim import gsx

    values = sim.gsx_values()
    if values is None:
        print("GSX: no answer for its L-vars (L-vars through SimConnect need MSFS 2020 SU12 or later)")
        return
    print("GSX: " + ", ".join(f"{name.removeprefix('L:FSDT_GSX_')}={value:g}" for name, value in values.items())
          + ("" if gsx.state_from_lvars(values) else "  (GSX not running: COUATL_STARTED is 0)"))
    if open_menu:
        sim.set_lvar(gsx.MENU_OPEN, 1)
        time.sleep(2)
        path = gsx.menu_file()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            print(f"GSX menu ({path}):", *lines, sep="\n  ")
        except OSError as e:
            print(f"GSX menu file not readable: {e}")


def check_tuning(sim: SimConnectSource, mhz: float) -> None:
    """COM1 set through the COM_RADIO_SET_HZ key event (C2), then read back."""
    sim.set_com1(round(mhz * 1000))
    time.sleep(1)
    print(f"COM1 set to {mhz:.3f}: now {sim.read().com1_khz / 1000:.3f}")


def traffic_summary(traffic) -> str:
    """One line to tell whose traffic it is: LiveTraffic and FSLTL carry real callsigns and FSLTL models."""
    ground = [t for t in traffic if t.on_ground]
    rolling = [t for t in ground if t.ground_speed_kt > 3]
    airline = [t for t in traffic if t.airline and t.flight_number]
    fsltl = [t for t in traffic if "fsltl" in t.title.lower()]
    return (f"       {len(ground)} on the ground ({len(rolling)} moving), {len(traffic) - len(ground)} in the air; "
            f"{len(airline)} with airline and flight number, {len(fsltl)} FSLTL models")


if __name__ == "__main__":
    raise SystemExit(main())
