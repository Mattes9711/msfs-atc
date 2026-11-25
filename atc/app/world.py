"""Builds atc/app/static/world.json: land, lakes and country borders for the map, so it looks like a map offline.

Source: Natural Earth (https://www.naturalearthdata.com, public domain), 1:50 million, the GeoJSON copies in
https://github.com/nvkelso/natural-earth-vector/tree/master/geojson:
    ne_50m_land.geojson                           the land (the sea is the map's background)
    ne_50m_lakes.geojson                          the big lakes, drawn over the land
    ne_50m_admin_0_boundary_lines_land.geojson    the borders between countries on land
1:50 million is about a kilometre: right from the whole of Europe down to a 20 NM view; closer in, the airport's own
data (runways, taxiways) is what counts.

The file keeps each line as a flat list [lat, lon, lat, lon, ...] rounded to DECIMALS, with points closer than
MIN_STEP degrees to the last one left out, and the box [s, w, n, e] of each, so the page skips what is out of view.

Not run by the app. Rebuild the file from the three files downloaded before:  python -m atc.app.world <folder>
"""
import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).parent / "static" / "world.json"
FILES = {"land": "ne_50m_land.geojson", "lakes": "ne_50m_lakes.geojson",
         "borders": "ne_50m_admin_0_boundary_lines_land.geojson"}
DECIMALS = 2  # 0.01 degree: 0.6 NM north-south, finer than the source
MIN_STEP = 0.02  # degrees between two kept points (the 1:50 million lines are about this fine)
LICENCE = "Natural Earth (https://www.naturalearthdata.com), public domain. Made with Natural Earth."


def lines_of(geometry: dict) -> list[list[list[float]]]:
    """The outer and inner rings of a (Multi)Polygon, the parts of a (Multi)LineString, as [lon, lat] lists."""
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "Polygon":
        return list(coords)
    if kind == "MultiPolygon":
        return [ring for polygon in coords for ring in polygon]
    if kind == "LineString":
        return [coords]
    if kind == "MultiLineString":
        return list(coords)
    return []


def compact(points: list[list[float]], closed: bool) -> dict | None:
    """{"box": [s, w, n, e], "line": [lat, lon, ...]}, thinned; None when too little is left to draw."""
    kept: list[tuple[float, float]] = []
    for lon, lat, *_ in points:
        p = (round(lat, DECIMALS), round(lon, DECIMALS))
        if kept and abs(p[0] - kept[-1][0]) < MIN_STEP and abs(p[1] - kept[-1][1]) < MIN_STEP:
            continue
        kept.append(p)
    if closed and kept and kept[-1] != kept[0]:
        kept.append(kept[0])
    if len(kept) < (4 if closed else 2):
        return None
    lats, lons = [p[0] for p in kept], [p[1] for p in kept]
    return {"box": [min(lats), min(lons), max(lats), max(lons)], "line": [v for p in kept for v in p]}


def build(geojson: dict[str, dict]) -> dict:
    """{"licence", "land", "lakes", "borders"} from the three parsed GeoJSON files."""
    out: dict = {"licence": LICENCE}
    for name, data in geojson.items():
        closed = name != "borders"
        found = (compact(line, closed) for f in data["features"] if f.get("geometry")
                 for line in lines_of(f["geometry"]))
        out[name] = [x for x in found if x]
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    folder = Path(argv[0])
    world = build({name: json.loads((folder / file).read_text(encoding="utf-8")) for name, file in FILES.items()})
    OUTPUT.write_text(json.dumps(world, separators=(",", ":")), encoding="utf-8")
    print(f"{OUTPUT}: {OUTPUT.stat().st_size // 1024} KB, "
          + ", ".join(f"{len(world[k])} {k}" for k in FILES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
