"""Unit tests for matching City bike facilities against OSM.

Everything here is synthetic and metric: City lines and OSM ways are shapely
LineStrings in UTM metres. The OSM road runs east along y = Y0, so a City
line at Y0 + dy with dy > 0 lies on the road's LEFT, and the tag that speaks
for it is cycleway:left. What these pin is the rule in compare's docstring:
the side a lane is read on, the cross street that must not answer for it,
the buffer check, the path and route rules, and the statuses they add up to.
"""

import os
import sys
from datetime import date

import pytest
import shapely

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import compare, config  # noqa: E402

X0, Y0 = 500000.0, 4820000.0
TODAY = date(2026, 10, 24)


def _hline(x0, x1, dy=0.0):
    """A metric line along y = Y0 + dy, from X0 + x0 to X0 + x1."""
    return shapely.LineString([(X0 + x0, Y0 + dy), (X0 + x1, Y0 + dy)])


def _vline(x, y0, y1):
    """A metric line along x = X0 + x, from Y0 + y0 to Y0 + y1."""
    return shapely.LineString([(X0 + x, Y0 + y0), (X0 + x, Y0 + y1)])


def _city(ftype="Bike Lane", dy=6.0, length=200.0, status="in_service",
          onroad=True, year=2017, **props):
    kind = {"MUP": "mup", "Signed Route": "route", "Crossride": "spot",
            "Cycle Track": "separated"}.get(ftype, "painted")
    return {
        "props": {"id": 7, "status": status, "type": ftype, "kind": kind,
                  "onroad": onroad, "year": year, "street": "City St",
                  "length": int(length), **props},
        # Not reprojected by match(), only rounded into the gap feature.
        "geom": {"type": "LineString",
                 "coordinates": [[-80.25, 43.54], [-80.249, 43.54]]},
        "lines": [_hline(0, length, dy)],
    }


def _way(wid, g, **tags):
    return {"id": wid, "tags": tags, "g": g}


def _road(wid=1, length=200.0, **tags):
    tags.setdefault("highway", "secondary")
    tags.setdefault("name", "Main Street")
    return _way(wid, _hline(-5, length + 5), **tags)


def _osm(road=(), path=(), route=()):
    path = list(path)
    return {"road": list(road), "path": path,
            "bikeway": [w for w in path if compare.is_bikeway(w["tags"])],
            "route": list(route)}


def _one(city_item, osm):
    gaps, _summary = compare.match([city_item], osm, today=TODAY)
    assert len(gaps) <= 1
    return gaps[0]["properties"] if gaps else None


def _status(city_item, osm):
    p = _one(city_item, osm)
    return p["status"] if p else None


# --- reading a road's tags --------------------------------------------------

@pytest.mark.parametrize("tags, side, value", [
    ({"cycleway:left": "lane"}, "left", "lane"),
    ({"cycleway:left": "lane"}, "right", None),
    ({"cycleway:both": "lane", "cycleway:right": "no"}, "right", "no"),
    ({"cycleway:both": "track"}, "left", "track"),
    ({"cycleway": "lane"}, "left", "lane"),
    # On a oneway road a plain cycleway=lane is the right-hand lane only.
    ({"cycleway": "lane", "oneway": "yes"}, "left", None),
    ({"cycleway": "lane", "oneway": "yes"}, "right", "lane"),
    ({}, "left", None),
])
def test_side_value(tags, side, value):
    assert compare.side_value(tags, side) == value


@pytest.mark.parametrize("tags, side, state", [
    ({"cycleway:left": "lane"}, "left", "pos"),
    ({"cycleway:left": "separate"}, "left", "pos"),
    ({"cycleway:left": "no"}, "left", "no"),
    ({"cycleway:both": "no"}, "left", "no"),
    ({}, "left", "absent"),
    ({"bicycle": "designated"}, "left", "pos"),
    # Any side: positive when any key is.
    ({"cycleway:right": "lane"}, "any", "pos"),
    ({"cycleway:right": "no", "cycleway:left": "lane"}, "any", "pos"),
    ({"cycleway:both": "no"}, "any", "no"),
])
def test_lane_state(tags, side, state):
    assert compare.lane_state(tags, side) == state


def test_a_contraflow_lane_accepts_oneway_bicycle_no():
    tags = {"oneway": "yes", "oneway:bicycle": "no"}
    assert compare.lane_state(tags, "left") == "absent"
    assert compare.lane_state(tags, "left", contraflow=True) == "pos"


@pytest.mark.parametrize("tags, side, buffer, ok", [
    ({"cycleway:left:separation": "kerb"}, "left", "Curbed", True),
    ({"cycleway:both:separation:left": "bollard"}, "left", "Bollard", True),
    ({"cycleway:right:separation": "kerb"}, "left", "Curbed", False),
    ({"cycleway:left:buffer": "yes"}, "left", "Painted", True),
    ({"cycleway:left": "track"}, "left", "Curbed", True),
    # A track is a curb, not paint: it says nothing about a painted buffer.
    ({"cycleway:left": "track"}, "left", "Painted", False),
    ({"cycleway:left": "separate"}, "left", "Curbed", True),
    ({"cycleway:right:separation": "kerb"}, "any", "Curbed", True),
    ({}, "left", "Curbed", False),
])
def test_has_separation(tags, side, buffer, ok):
    assert compare.has_separation(tags, side, buffer) is ok


@pytest.mark.parametrize("tags, access", [
    ({"highway": "footway", "footway": "sidewalk"}, "nobike"),
    ({"highway": "footway", "bicycle": "yes"}, "ok"),
    ({"highway": "path"}, "ok"),
    ({"highway": "path", "bicycle": "no"}, "nobike"),
    ({"highway": "cycleway"}, "ok"),
    ({"highway": "pedestrian"}, "nobike"),
])
def test_bike_access(tags, access):
    assert compare.bike_access(tags) == access


# --- on-road lanes ----------------------------------------------------------

def test_a_lane_on_its_tagged_side_is_not_listed():
    assert _status(_city(), _osm([_road(**{"cycleway:left": "lane"})])) is None


def test_a_lane_tagged_on_the_other_side_only_is_missing():
    p = _one(_city(), _osm([_road(**{"cycleway:right": "lane"})]))
    assert p["status"] == "missing"
    assert p["side"] == "left" and p["way"] == 1
    assert p["tag"] == "cycleway:left=lane"
    assert p["untraced"] == 200 and p["street"] == "Main Street"


def test_the_side_follows_the_way_direction():
    # The same City line, the road drawn westward: now it is the right side.
    road = _way(1, shapely.reverse(_hline(-5, 205)), highway="secondary",
                **{"cycleway:right": "lane"})
    assert _status(_city(), _osm([road])) is None


def test_a_lane_where_the_road_says_no_is_says_no():
    p = _one(_city(), _osm([_road(**{"cycleway:both": "no"})]))
    assert p["status"] == "says_no" and p["tag"] == "cycleway:left=lane"


def test_a_recent_install_is_new_and_keeps_its_kind():
    p = _one(_city(year=2025), _osm([_road(**{"cycleway:both": "no"})]))
    assert p["status"] == "new" and p["gap"] == "says_no"
    p = _one(_city(year=2024), _osm([_road()]))
    assert p["status"] == "missing" and "gap" not in p


def test_no_road_at_all_is_missing():
    assert _status(_city(), _osm()) == "missing"


def test_a_lane_on_the_centreline_is_judged_on_any_side():
    city = _city(dy=1.0)
    assert _status(city, _osm([_road(**{"cycleway:right": "lane"})])) is None
    p = _one(city, _osm([_road()]))
    assert p["side"] == "any"
    assert p["tag"].startswith("cycleway:<left|right>=lane")
    assert "check the side" in p["tag"]


def test_a_cross_street_does_not_answer_for_a_lane():
    # A north-south road 8 m off the end of the lane, tagged with lanes; the
    # lane's own road is not mapped. Nearest-road would call the end covered.
    cross = _way(2, _vline(208, -100, 100), highway="secondary",
                 **{"cycleway:both": "lane"})
    city = _city(length=40.0)
    city["lines"] = [_hline(170, 210, 6.0)]
    p = _one(city, _osm([cross]))
    assert p["status"] == "missing" and p["untraced"] == 40


def test_the_lanes_own_road_wins_over_a_nearer_cross_street():
    cross = _way(2, _vline(100, -100, 100), highway="residential",
                 **{"cycleway:both": "no"})
    own = _road(**{"cycleway:left": "lane"})
    assert _status(_city(), _osm([cross, own])) is None


def test_a_separate_cycleway_beside_the_lane_covers_it():
    track = _way(5, _hline(-5, 205, 9.0), highway="cycleway")
    assert _status(_city(), _osm([_road()], [track])) is None


def test_a_green_contraflow_and_buffered_lane_get_their_extra_tags():
    p = _one(_city(ftype="Bike Lane - Green", buffer="Painted"), _osm([_road()]))
    assert p["tag"] == ("cycleway:left=lane + cycleway:left:surface:colour=green"
                        " + cycleway:left:buffer=yes")
    p = _one(_city(ftype="Contraflow"), _osm([_road()]))
    assert p["tag"] == ("cycleway:left=lane + cycleway:left:oneway=-1"
                        " + oneway:bicycle=no")
    p = _one(_city(ftype="Cycle Track"), _osm([_road()]))
    assert p["tag"] == "cycleway:left=track"


# --- separation -------------------------------------------------------------

def test_a_curbed_lane_without_a_separation_tag_is_nosep():
    p = _one(_city(buffer="Curbed"), _osm([_road(**{"cycleway:left": "lane"})]))
    assert p["status"] == "nosep"
    assert p["tag"] == "cycleway:left:separation=kerb"
    assert p["way"] == 1 and p["untraced"] == 0


@pytest.mark.parametrize("tags", [
    {"cycleway:left": "lane", "cycleway:left:separation": "kerb"},
    {"cycleway:left": "track"},
])
def test_a_curbed_lane_with_its_separation_is_not_listed(tags):
    assert _status(_city(buffer="Curbed"), _osm([_road(**tags)])) is None


def test_a_painted_buffer_wants_the_buffer_key():
    city = _city(buffer="Painted")
    assert _status(city, _osm([_road(**{"cycleway:left": "lane"})])) == "nosep"
    assert _status(city, _osm([_road(**{"cycleway:left": "lane",
                                         "cycleway:left:buffer": "yes"})])) is None


def test_a_missing_buffered_lane_is_missing_not_nosep():
    p = _one(_city(buffer="Rumble Strip"), _osm([_road()]))
    assert p["status"] == "missing"
    assert p["tag"] == ("cycleway:left=lane + "
                        "cycleway:left:separation=rumble_strip")


# --- off-road paths ---------------------------------------------------------

def _mup(**kw):
    return _city(ftype="MUP", onroad=False, dy=0.0, **kw)


def test_a_mup_on_a_shared_path_is_not_listed():
    path = _way(3, _hline(-5, 205, 3.0), highway="path", bicycle="designated")
    assert _status(_mup(), _osm(path=[path])) is None


def test_a_mup_mapped_as_a_sidewalk_is_nobike():
    sidewalk = _way(3, _hline(-5, 205, 3.0), highway="footway",
                    footway="sidewalk")
    p = _one(_mup(), _osm(path=[sidewalk]))
    assert p["status"] == "nobike" and p["way"] == 3
    assert p["tag"] == "bicycle=designated + segregated=no"


def test_a_mup_with_no_path_is_missing():
    p = _one(_mup(), _osm())
    assert p["status"] == "missing"
    assert p["tag"].startswith("highway=path + bicycle=designated")


def test_a_cycle_track_beside_a_sidewalk_finds_the_cycleway():
    # The sidewalk is nearer; the cycleway 9 m off is what maps the track.
    city = _city(ftype="Cycle Track", onroad=False, dy=0.0)
    sidewalk = _way(3, _hline(-5, 205, 2.0), highway="footway",
                    footway="sidewalk")
    cycleway = _way(4, _hline(-5, 205, -9.0), highway="cycleway")
    assert _status(city, _osm(path=[sidewalk, cycleway])) is None
    p = _one(city, _osm(path=[sidewalk]))
    assert p["status"] == "nobike" and p["tag"].startswith("highway=cycleway")


def test_an_off_road_cycle_track_is_covered_by_a_track_tag_on_the_road():
    city = _city(ftype="Cycle Track", onroad=False, dy=8.0)
    assert _status(city, _osm([_road(**{"cycleway:left": "track"})])) is None


# --- signed routes ----------------------------------------------------------

def _route(**kw):
    return _city(ftype="Signed Route", dy=0.0, **kw)


def test_a_signed_route_on_a_relation_is_not_listed():
    member = _way(90, _hline(-5, 205), route="bicycle", network="lcn")
    assert _status(_route(), _osm([_road()], route=[member])) is None


def test_a_signed_route_tagged_designated_on_the_road_is_not_listed():
    road = _road(bicycle="designated", **{"cycleway:both": "no"})
    assert _status(_route(), _osm([road])) is None


def test_a_signed_route_with_nothing_is_unsigned():
    p = _one(_route(), _osm([_road()]))
    assert p["status"] == "unsigned_route"
    assert p["tag"].startswith("route=bicycle relation")
    p = _one(_route(year=2026), _osm([_road()]))
    assert p["status"] == "new" and p["gap"] == "unsigned_route"


# --- what is listed, and what is counted ------------------------------------

def test_crossrides_are_listed_as_spot_and_never_counted():
    city = _city(ftype="Crossride", length=12.0, year=2026)
    gaps, summary = compare.match([city], _osm(), today=TODAY)
    assert [g["properties"]["status"] for g in gaps] == ["spot"]
    assert summary["spot"] == 1 and summary["work"] == 0
    assert summary["new"] == 0 and summary["city"] == 0


def test_a_planned_lane_is_planned_unless_osm_has_it():
    assert _status(_city(status="planned", year=2026), _osm()) == "planned"
    assert _status(_city(status="planned"),
                   _osm([_road(**{"cycleway:left": "lane"})])) is None


def test_an_out_of_service_lane_is_not_listed():
    assert _status(_city(status="out_of_service"), _osm()) is None


def test_a_short_gap_is_not_listed():
    # A protected-intersection corner piece.
    assert _status(_city(length=10.0), _osm()) is None
    assert _status(_city(length=20.0), _osm()) == "missing"


def test_the_summary_adds_up():
    lanes = [_city(), _city(dy=-6.0)]
    lanes[1]["props"]["id"] = 8
    osm = _osm([_road(**{"cycleway:left": "lane", "cycleway:right": "no"})])
    gaps, s = compare.match(lanes, osm, today=TODAY)
    assert s["lane_km"] == 0.4 and s["lane_pos_km"] == 0.2
    assert s["lane_no_km"] == 0.2 and s["lane_absent_km"] == 0.0
    assert s["says_no"] == 1 and s["work"] == 1
    assert s["recent_since"] == 2025
    assert [g["properties"]["side"] for g in gaps] == ["right"]
