"""The console: python -m atc. Setup is in atc/session.py and the loops in atc/runtime.py, shared with the app."""
import argparse
import time
from pathlib import Path
from typing import Callable

from atc.airport.model import AirportData
from atc.airspace.centers import CenterSectors
from atc.audio.base import SpeechInput, SpeechOutput
from atc.audio.text import PrintOutput, TextInput
from atc.audio import setup
from atc.audio.tts import TtsError
from atc.audio.voice import list_mics
from atc.config import Config, ConfigError, load_config
from atc import paths
from atc.app.server import binding_name
from atc.events import ConsoleSink, Tee
from atc.flightlog import FlightLog, log_path
from atc.runtime import HELP, run, run_live
from atc.session import PlanRequest, SessionOptions, SetupError, SimbriefLoader, build_session
from atc.sim.base import SimSource
from atc.sim.fake import FakeSim
from atc.units import parse_level
from atc.weather.source import WeatherSource

VoiceFactory = Callable[[Config], tuple[list[SpeechInput], SpeechOutput]]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m atc", description="Voice ATC for MSFS2020")
    p.add_argument("--text", action="store_true", help="type transmissions instead of push-to-talk")
    p.add_argument("--list-mics", action="store_true", help="list input devices (for [whisper] mic) and exit")
    p.add_argument("--nosim", action="store_true", help="use a fake sim instead of MSFS")
    p.add_argument("--config", type=Path,
                   help="settings file (default: settings.toml in %%APPDATA%%\\MSFS ATC, if present)")
    p.add_argument("--strict-freq", action="store_true", help="wrong frequency = silence, no hint")
    p.add_argument("--weather", choices=("live", "sim"), default="live",
                   help="live: real METAR (default); sim: wind, visibility and QNH from MSFS at the aircraft")
    fp = p.add_argument_group("flight plan", "Use --simbrief, or give at least --callsign (and --from with "
                                             "--nosim; with MSFS the airport you are at is detected). "
                                             "Values given here override the SimBrief plan.")
    fp.add_argument("--simbrief", nargs="?", const="", metavar="USER",
                    help="load your latest SimBrief plan (USER defaults to simbrief_username in settings.toml)")
    fp.add_argument("--callsign", help="e.g. DLH4AB")
    fp.add_argument("--from", dest="departure", help="departure ICAO, e.g. EDDH")
    fp.add_argument("--to", dest="destination", help="destination ICAO")
    fp.add_argument("--cruise", type=parse_level, help="e.g. FL240 or 5000")
    fp.add_argument("--route", default="", help='e.g. "AMLU2G AMLUH M852 DENIX"')
    fp.add_argument("--aircraft", help="ICAO type, e.g. A20N")
    return p


def main(argv: list[str] | None = None, weather: WeatherSource | None = None,
         airports: list[AirportData] | None = None, simbrief: SimbriefLoader | None = None,
         centers: CenterSectors | None = None, connect_sim: Callable[[], SimSource] | None = None,
         voice: VoiceFactory | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_mics:
        print("\n".join(list_mics()))
        return
    request = PlanRequest(simbrief=args.simbrief, callsign=args.callsign, departure=args.departure,
                          destination=args.destination, cruise_ft=args.cruise, route=args.route,
                          aircraft=args.aircraft)
    options = SessionOptions(nosim=args.nosim, weather=args.weather, strict_freq=args.strict_freq)
    try:
        config = load_config(args.config)
        session = build_session(request, options, config, weather=weather, airports=airports, simbrief=simbrief,
                                centers=centers, connect_sim=connect_sim)
    except (ConfigError, SetupError) as e:
        parser.error(str(e))
    print("\n".join(session.banner()))

    if args.text:
        inputs, output = [TextInput()], PrintOutput()
    else:
        try:
            inputs, output = (voice or build_voice)(config)
        except (setup.VoiceUnavailable, TtsError, OSError) as e:
            session.close()
            parser.error(str(e))
        print(f"Push-to-talk: hold [{binding_name(config.whisper.ptt_key)}] while you speak. "
              "Type /commands at any time.")
    for source in inputs:  # push-to-talk gets this flight's words for whisper
        if hasattr(source, "context"):
            source.context = session.controller.speech_context
    print(HELP)
    flight_log = FlightLog(log_path(paths.logs_dir(), session.plan.callsign, time.time()), session.banner())
    print(f"Flight log: {flight_log.path}")
    sink = Tee(ConsoleSink(output), flight_log)
    try:
        if args.text and isinstance(session.sim, FakeSim):
            run(session.sim, inputs[0], sink, session.controller, session.cabin())
        else:
            run_live(session.sim, inputs, sink, session.controller, refresh=session.refresh_weather,
                     winds=session.winds if options.weather == "sim" else None, cabin=session.cabin(),
                     gsx=session.gsx())
    except KeyboardInterrupt:
        pass
    finally:
        flight_log.close()
        session.close()
        getattr(output, "close", lambda: None)()


def build_voice(config: Config) -> tuple[list[SpeechInput], SpeechOutput]:
    """Push-to-talk + whisper in, Zira out; the keyboard stays open for /commands."""
    setup.make_recorder(config)  # checks the key name before the slow model load
    transcriber = setup.load_transcriber(config, lambda text: print(text, flush=True))
    output = setup.make_tts(config, progress=lambda text: print(text, flush=True))
    output.hold = setup.ptt_held(config)
    print(f"ATC voice: {output.voice_name}")
    return [setup.make_whisper_input(config, transcriber), TextInput(prompt="")], output
