"""Spike (step 6): fetch the latest SimBrief flight plan by username and save it as a test fixture."""
import argparse
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

URL = "https://www.simbrief.com/api/xml.fetcher.php?username={}"
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "cache" / "simbrief_latest.xml"
FIXTURE = ROOT / "tests" / "fixtures" / "simbrief_sample.xml"
# Only what the ATC needs; drops user IDs, crew names, personal links/prefile URLs and the bulky NOTAMs
KEEP = ["general", "origin", "destination", "alternate", "navlog", "atc", "aircraft"]

FIELDS = {
    "callsign": "atc/callsign",
    "flight rules": "atc/flight_rules",
    "aircraft": "aircraft/icaocode",
    "origin": "origin/icao_code",
    "origin runway": "origin/plan_rwy",
    "destination": "destination/icao_code",
    "destination runway": "destination/plan_rwy",
    "cruise altitude": "general/initial_altitude",
    "route": "general/route",
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("username")
    args = p.parse_args()

    try:
        with urllib.request.urlopen(URL.format(urllib.parse.quote(args.username)), timeout=15) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        status = ET.fromstring(body).findtext("fetch/status") if body.startswith(b"<") else None
        raise SystemExit(f"SimBrief HTTP {e.code}: {status or body[:300]!r}")
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_bytes(data)
    print(f"Saved full response ({len(data)} bytes) to {RAW.relative_to(ROOT)}")

    root = ET.fromstring(data)
    trimmed = ET.Element("OFP")
    for tag in KEEP:
        if (section := root.find(tag)) is not None:
            for notams in section.findall("notam"):
                section.remove(notams)
            trimmed.append(section)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(trimmed).write(FIXTURE, encoding="utf-8", xml_declaration=True)
    print(f"Saved trimmed fixture ({FIXTURE.stat().st_size} bytes) to {FIXTURE.relative_to(ROOT)}")

    for label, path in FIELDS.items():
        print(f"{label:20} {root.findtext(path)}")


if __name__ == "__main__":
    main()
