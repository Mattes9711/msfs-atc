"""Export airports from Little Navmap to JSON, so they work without Little Navmap (tests, other machines).

Usage: python -m atc.airport.export EDDH [EDDM ...] [--out data/airports]

LICENCE: the export is derived from the user's installed scenery (see littlenavmap.py). Fine for tests and for the
user's own machines; it must not be published or bundled with the app. data/airports/ is test data only.
"""
import argparse
from pathlib import Path

from atc.airport.json_data import JsonAirportData
from atc.airport.littlenavmap import LittleNavmapAirportData
from atc.config import load_config


def main(argv: list[str] | None = None) -> None:
    config = load_config()
    p = argparse.ArgumentParser(prog="python -m atc.airport.export")
    p.add_argument("idents", nargs="+", metavar="ICAO")
    p.add_argument("--out", type=Path, default=config.airports_dir)
    args = p.parse_args(argv)
    if not config.littlenavmap_db.exists():
        p.error(f"Little Navmap database not found: {config.littlenavmap_db}")

    source, target = LittleNavmapAirportData(config.littlenavmap_db), JsonAirportData(args.out)
    for ident in args.idents:
        airport = source.get(ident)
        if airport is None:
            print(f"{ident}: not in the Little Navmap database")
            continue
        print(f"{ident}: wrote {target.save(airport)}")


if __name__ == "__main__":
    main()
