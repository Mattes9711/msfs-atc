"""L4: other aircraft in the way of our taxi route. Geometry in local metres, x east, y north."""
import pytest

from atc.controller.give_way import conflict, path_ahead, traffic_name, type_word

NORTH = [(0.0, 0.0), (0.0, 500.0), (0.0, 1000.0)]  # our route straight north


def test_only_the_route_ahead_counts():
    path = path_ahead(NORTH, (5.0, 300.0), 300)
    assert path[0] == (0.0, 300.0) and path[-1] == (0.0, 600.0)


@pytest.mark.parametrize("at, heading, kind, direction", [
    ((-200.0, 200.0), 90, "crossing", "left to right"),  # from the west, heading east, will cross at 200 m
    ((200.0, 200.0), 270, "crossing", "right to left"),
    ((0.0, 150.0), 0, "follow", None),  # ahead on our route, going our way
    ((0.0, 150.0), 180, "opposite", None),  # ahead on our route, coming towards us
    ((5.0, 100.0), 90, "crossing", "left to right"),  # crossing right now, on the route
])
def test_kinds_of_conflict(at, heading, kind, direction):
    c = conflict(path_ahead(NORTH, (0.0, 0.0), 300), at, heading, 15)
    assert (c.kind, c.direction) == (kind, direction)


def test_no_conflict():
    path = path_ahead(NORTH, (0.0, 0.0), 300)
    assert conflict(path, (-200.0, 200.0), 270, 15) is None  # moving away from our route
    assert conflict(path, (-200.0, 200.0), 90, 2) is None  # too slow to get there in 30 s
    assert conflict(path, (0.0, -100.0), 0, 15) is None  # behind us
    assert conflict(path, (-200.0, 900.0), 90, 15) is None  # crosses beyond the part ahead


def test_how_traffic_is_named():
    assert traffic_name("AFR49KP", "Air France", "A220") == "the Airfrans Airbus"
    assert traffic_name("DLH1AL", "Lufthansa", "A20N") == "the Lufthansa Airbus"
    assert traffic_name("NOZ26F", "Norwegian", "737") == "the Norwegian Boeing"
    assert traffic_name("D-ANCH", "", "Skyhawk") == "the Skyhawk"
    assert traffic_name("D-AXUU", "", "152") == "the traffic"
    assert type_word("B738") == "Boeing" and type_word("E190") == "Embraer" and type_word("CRJ9") == ""
