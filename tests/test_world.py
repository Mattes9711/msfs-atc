"""The builder of the map's land, lakes and borders (atc/app/world.py)."""
import json

from atc.app import world


def square(s, w, n, e):
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]


def test_compact_rounds_thins_and_boxes():
    points = [[9.0, 53.0], [9.001, 53.001], [9.5, 53.0], [9.5, 53.5], [9.0, 53.5], [9.0, 53.0]]
    out = world.compact(points, closed=True)
    assert out == {"box": [53.0, 9.0, 53.5, 9.5], "line": [53.0, 9.0, 53.0, 9.5, 53.5, 9.5, 53.5, 9.0, 53.0, 9.0]}


def test_compact_closes_rings_and_drops_what_is_too_small():
    assert world.compact([[9.0, 53.0], [9.5, 53.0], [9.5, 53.5]], closed=True)["line"][-2:] == [53.0, 9.0]
    assert world.compact([[9.0, 53.0], [9.001, 53.001], [9.002, 53.0]], closed=True) is None
    assert world.compact([[9.0, 53.0]], closed=False) is None
    assert world.compact([[9.0, 53.0], [10.0, 54.0]], closed=False)["line"] == [53.0, 9.0, 54.0, 10.0]


def test_build_reads_every_geometry_kind():
    feature = lambda kind, coords: {"type": "Feature", "geometry": {"type": kind, "coordinates": coords}}
    data = {
        "land": {"features": [feature("Polygon", [square(50, 5, 52, 8)]),
                              feature("MultiPolygon", [[square(40, 0, 41, 1)], [square(60, 10, 61, 12)]]),
                              {"type": "Feature", "geometry": None}]},
        "lakes": {"features": [feature("Polygon", [square(47.5, 9, 47.7, 9.7)])]},
        "borders": {"features": [feature("LineString", [[6, 50], [7, 51]]),
                                 feature("MultiLineString", [[[8, 47], [9, 48]], [[1, 1], [1.001, 1.001]]])]},
    }
    out = world.build(data)
    assert out["licence"] == world.LICENCE
    assert [x["box"] for x in out["land"]] == [[50, 5, 52, 8], [40, 0, 41, 1], [60, 10, 61, 12]]
    assert len(out["lakes"]) == 1
    assert [x["line"] for x in out["borders"]] == [[50, 6, 51, 7], [47, 8, 48, 9]]
    json.dumps(out)


def test_the_shipped_file_is_there_and_credits_natural_earth():
    data = json.loads(world.OUTPUT.read_text(encoding="utf-8"))
    assert "Natural Earth" in data["licence"]
    assert data["land"] and data["lakes"] and data["borders"]
