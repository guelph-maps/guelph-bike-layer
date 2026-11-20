"""Regression tests for matching bike lanes near motorway ramps."""

import os
import sys

import shapely

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import compare  # noqa: E402


def _city():
    return {
        "props": {"id": 321, "status": "in_service", "type": "Bike Lane",
                  "kind": "painted", "onroad": True, "year": 2011,
                  "street": "Laird Road"},
        "geom": {"type": "LineString", "coordinates": [[-80.25, 43.54],
                                                       [-80.249, 43.54]]},
        "lines": [shapely.LineString([(500000, 4820006), (500100, 4820006)])],
    }


def _road(wid, y, **tags):
    return {"id": wid, "tags": tags,
            "g": shapely.LineString([(499995, 4820000 + y),
                                     (500105, 4820000 + y)])}


def _match(roads):
    osm = {"road": roads, "path": [], "bikeway": [], "route": []}
    return compare.match([_city()], osm)


def test_parallel_motorway_ramp_does_not_hide_lane_on_adjacent_road():
    ramp = _road(1, 5, highway="motorway_link")
    street = _road(2, 0, highway="secondary", name="Laird Road",
                   **{"cycleway:left": "lane"})

    gaps, _ = _match([ramp, street])

    assert gaps == []


def test_parallel_ramp_does_not_hide_a_genuine_missing_lane():
    ramp = _road(1, 5, highway="motorway_link")
    street = _road(2, 0, highway="secondary", name="Laird Road")

    gaps, _ = _match([ramp, street])

    assert gaps[0]["properties"]["status"] == "missing"
    assert gaps[0]["properties"]["way"] == 2
    assert gaps[0]["properties"]["side"] == "left"


def test_ramp_remains_a_candidate_when_no_other_road_matches():
    ramp = _road(1, 5, highway="motorway_link")

    gaps, _ = _match([ramp])

    assert gaps[0]["properties"]["status"] == "missing"
    assert gaps[0]["properties"]["way"] == 1


def test_unaligned_road_does_not_replace_ramp():
    ramp = _road(1, 5, highway="motorway_link")
    cross = {"id": 2, "tags": {"highway": "secondary", "name": "Laird Road",
                               "cycleway:both": "lane"},
             "g": shapely.LineString([(500050, 4819990), (500050, 4820020)])}

    gaps, _ = _match([ramp, cross])

    assert gaps[0]["properties"]["way"] == 1


def test_nearby_other_ramp_is_not_preferred():
    ramp = _road(1, 5, highway="motorway_link")
    other_ramp = _road(2, 0, highway="trunk_link", name="Laird Road",
                       **{"cycleway:left": "lane"})

    gaps, _ = _match([ramp, other_ramp])

    assert gaps[0]["properties"]["way"] == 1


def test_an_explicit_no_on_the_street_is_not_hidden_by_ramp():
    ramp = _road(1, 5, highway="motorway_link")
    street = _road(2, 0, highway="secondary", name="Laird Road",
                   **{"cycleway:left": "no"})

    gaps, _ = _match([ramp, street])

    assert gaps[0]["properties"]["status"] == "says_no"
    assert gaps[0]["properties"]["way"] == 2


def test_unrelated_parallel_street_does_not_replace_ramp():
    ramp = _road(1, 5, highway="motorway_link")
    street = _road(2, 0, highway="secondary", name="Other Road",
                   **{"cycleway:left": "lane"})

    gaps, _ = _match([ramp, street])

    assert gaps[0]["properties"]["way"] == 1


def test_street_name_comparison_ignores_case_and_extra_whitespace():
    ramp = _road(1, 5, highway="motorway_link")
    street = _road(2, 0, highway="secondary", name="  LAIRD   road ",
                   **{"cycleway:left": "lane"})

    gaps, _ = _match([ramp, street])

    assert gaps == []
