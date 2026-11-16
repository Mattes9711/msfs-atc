import io
import urllib.error

import pytest

from atc.config import ROOT
from atc.flightplan.simbrief import SimbriefError, load_simbrief, parse_simbrief

SAMPLE = (ROOT / "tests" / "fixtures" / "simbrief_sample.xml").read_bytes()
NO_PLAN = b"<OFP><fetch><status>Error: No flight plan on file for the specified user</status></fetch></OFP>"


def test_parse_real_ofp():
    plan = parse_simbrief(SAMPLE)
    assert (plan.callsign, plan.departure, plan.destination) == ("DLH759", "EDDH", "EDDM")
    assert (plan.aircraft, plan.cruise_ft, plan.rules) == ("A20N", 35000, "IFR")
    assert plan.route.startswith("AMLU2G AMLUH M852")


@pytest.mark.parametrize("xml", [b"not xml", b"<OFP><atc><callsign>DLH1</callsign></atc></OFP>"])
def test_unusable_plans_are_rejected(xml):
    with pytest.raises(SimbriefError):
        parse_simbrief(xml)


def test_successful_fetch_is_cached(tmp_path):
    plan, cached = load_simbrief("pilot", tmp_path, fetch=lambda url, timeout: SAMPLE)
    assert plan.callsign == "DLH759" and not cached
    assert (tmp_path / "pilot.xml").read_bytes() == SAMPLE


def test_simbrief_error_reason_is_shown(tmp_path):
    def no_plan(url, timeout):
        raise urllib.error.HTTPError(url, 400, "Bad Request", None, io.BytesIO(NO_PLAN))

    with pytest.raises(SimbriefError, match="No flight plan on file"):
        load_simbrief("pilot", tmp_path, fetch=no_plan)


def offline(url, timeout):
    raise urllib.error.URLError("no network")


def test_offline_uses_cached_plan(tmp_path):
    load_simbrief("pilot", tmp_path, fetch=lambda url, timeout: SAMPLE)
    plan, cached = load_simbrief("pilot", tmp_path, fetch=offline)
    assert plan.callsign == "DLH759" and cached


def test_offline_without_cache_is_an_error(tmp_path):
    with pytest.raises(SimbriefError, match="unreachable"):
        load_simbrief("pilot", tmp_path, fetch=offline)


def test_username_cannot_escape_the_cache_folder(tmp_path):
    load_simbrief("../evil", tmp_path, fetch=lambda url, timeout: SAMPLE)
    assert [p.name for p in tmp_path.iterdir()] == ["___evil.xml"]


def test_waypoints_with_their_positions_and_legs():
    plan = parse_simbrief(SAMPLE)
    assert (plan.sid, plan.star) == ("AMLU2G", "LAND2A")
    idents = [w.ident for w in plan.waypoints]
    assert "TOC" not in idents and "TOD" not in idents and "EDDM" not in idents  # computed points, airports
    assert [w.leg for w in plan.waypoints if w.ident in ("HAM", "DENIX", "LANDU", "MIQ")] == ["sid", "route", "route",
                                                                                               "star"]
    assert plan.route_points()[0].ident == "DENIX"
    miq = plan.waypoints[-1]
    assert (miq.ident, miq.lat, miq.lon) == ("MIQ", 48.570225, 11.597503)  # the navlog's pos_lat / pos_long
