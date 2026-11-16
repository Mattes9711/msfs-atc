"""Taxi clearances as a controller gives them (Milestone 7, part A): every named taxiway of the route in order, the
holding point by name when the route ends on a named stub, and the first runway crossing as a hold short (the
next one comes with each crossing clearance)."""
import re

from atc.airport.taxi import TaxiRoute
from atc.controller import readback as rb

STUB = re.compile(r"[A-Z]+\d+[A-Z]?")  # "A13", "L4", "Z5B": a stub to the runway; "N" is a whole taxiway


def route_names(route: TaxiRoute | None) -> list[str]:
    """Every named taxiway of the route in order. Pieces the scenery leaves unnamed are left out of the list, but
    the route is the same: before 2026-11-15 a route with over 30 % unnamed got no "via" at all (all of Hamburg)."""
    return route.taxiways if route is not None else []


def holding_point(route: TaxiRoute | None) -> str | None:
    """The holding point's name: the stub the route ends on ("A13"), None when it ends on an unnamed piece or a
    whole taxiway."""
    if route is None or not route.edges:
        return None
    last = route.edges[-1].name or route.point
    return last if last and STUB.fullmatch(last) else None


def route_hold_short(route: TaxiRoute | None) -> str | None:
    """A runway crossing always becomes a hold short, named route or not."""
    return route.crossings[0] if route and route.crossings else None


def taxi_items(route: TaxiRoute | None, runway: str) -> list[rb.Item]:
    names, point = route_names(route), holding_point(route)
    if point and names and names[-1] == point:
        names = names[:-1]  # "to holding point A13 … via E2, N4, N", not "via E2, N4, N, A13"
    return rb.taxi(runway, names, route_hold_short(route), point)


def taxi_clearance(route: TaxiRoute | None, runway: str) -> str:
    """'taxi to holding point Alfa one tree runway two six right, via Echo two, November, hold short runway …'."""
    return rb.instruction_text(taxi_items(route, runway))
