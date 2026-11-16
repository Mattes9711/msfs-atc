"""Spike (step 5): find the Little Navmap MSFS database and dump what it has for one airport."""
import argparse
import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(os.environ["APPDATA"]) / "ABarthel" / "little_navmap_db" / "little_navmap_msfs.sqlite"
TABLES = ["airport", "runway", "runway_end", "com", "ils", "taxi_path", "parking", "start"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("icao", nargs="?", default="EDDF")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--rows", type=int, default=3)
    args = p.parse_args()

    if not args.db.exists():
        folder = args.db.parent
        found = list(folder.glob("*.sqlite")) if folder.exists() else []
        raise SystemExit(f"No database at {args.db}. Found in folder: {[f.name for f in found]}")

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    existing = {r["name"] for r in con.execute("select name from sqlite_master where type='table'")}

    for table in TABLES:
        if table not in existing:
            print(f"\n## {table}: MISSING")
            continue
        cols = [r["name"] for r in con.execute(f"pragma table_info({table})")]
        print(f"\n## {table} columns: {cols}")

    airport = con.execute("select * from airport where ident = ?", (args.icao,)).fetchone()
    if airport is None:
        raise SystemExit(f"Airport {args.icao} not found")
    print(f"\n## airport {args.icao}: {dict(airport)}")

    for table in TABLES[1:]:
        if table not in existing:
            continue
        cols = [r["name"] for r in con.execute(f"pragma table_info({table})")]
        if "airport_id" not in cols:
            continue
        count = con.execute(f"select count(*) from {table} where airport_id = ?", (airport["airport_id"],)).fetchone()[0]
        print(f"\n## {table}: {count} rows for {args.icao}")
        for row in con.execute(f"select * from {table} where airport_id = ? limit ?", (airport["airport_id"], args.rows)):
            print(dict(row))


if __name__ == "__main__":
    main()
