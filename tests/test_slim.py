"""Tests for the slim step: which properties survive, the derived kind, and
the count guard."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config  # noqa: E402
import src.slim as slim_mod  # noqa: E402
from src.slim import facility_kind, slim, slim_props  # noqa: E402


def test_slim_props_keeps_the_useful_fields():
    props = slim_props({
        "OBJECTID": 214, "BIKEFACILITYID": 2680, "STATUS": "In Service",
        "STREETNAME": "Wyndham Street South", "FACILITYTYPE": "Bike Lane",
        "SURFACETYPE": "Asphalt", "ONROAD": "Yes", "FACILITYWIDTH": 1.5,
        "PAINTED": "Yes", "BUFFERTYPE": "Painted", "BUFFERWIDTH": 0.5,
        "SIGNED": "No", "INSTALLYEAR": 2026, "ASSETID": "X",
        "DATACAPTUREACCURACY": "0 to 1 metre", "Shape__Length": 84.6,
    })
    assert props == {"id": 2680, "status": "in_service", "type": "Bike Lane",
                     "kind": "buffered", "onroad": True, "buffer": "Painted",
                     "year": 2026, "width": 1.5, "signed": False,
                     "street": "Wyndham Street South", "length": 85}


@pytest.mark.parametrize("raw, expected", [
    ("In Service", "in_service"), (" In Service ", "in_service"),
    ("Planned", "planned"), ("Out of Service", "out_of_service"),
    ("", "out_of_service"), (None, "out_of_service"),
])
def test_status(raw, expected):
    assert slim_props({"STATUS": raw})["status"] == expected


@pytest.mark.parametrize("ftype, buffer, kind", [
    ("Bike Lane", "", "painted"),
    ("Bike Lane - Green", "", "painted"),
    ("Contraflow", "", "painted"),
    ("Bike Lane", "Painted", "buffered"),
    ("Bike Lane", "Rumble Strip", "buffered"),
    ("Bike Lane", "Curbed", "separated"),
    ("Bike Lane", "Rolled Curb", "separated"),
    ("Contraflow", "Barrier and Bollard", "separated"),
    ("Bike Lane", "Bollard", "separated"),
    ("Cycle Track", "", "separated"),
    ("Cycle Track", "Painted", "separated"),
    ("MUP", "Curbed", "mup"),
    ("Signed Route", "", "route"),
    ("Crossride", "", "spot"),
    ("Bike Lane - Intersection", "", "spot"),
    ("Left-Turn Curb Cut", "", "spot"),
    ("Other", "", "spot"),
])
def test_facility_kind(ftype, buffer, kind):
    assert facility_kind(ftype, buffer) == kind


@pytest.mark.parametrize("raw", ["None", "Other", "", None])
def test_no_buffer_leaves_no_field(raw):
    props = slim_props({"FACILITYTYPE": "Bike Lane", "BUFFERTYPE": raw})
    assert "buffer" not in props and props["kind"] == "painted"


def test_onroad_and_signed():
    assert slim_props({"ONROAD": "No"})["onroad"] is False
    assert slim_props({"ONROAD": "Yes", "SIGNED": "Yes"})["signed"] is True
    assert "signed" not in slim_props({"SIGNED": None})


def test_slim_props_tolerates_an_empty_row():
    assert slim_props({}) == {"status": "out_of_service", "type": "Other",
                              "kind": "spot", "onroad": False}


# --- the whole file ---------------------------------------------------------

def _line(fid, status="In Service", ftype="Bike Lane", year=2024,
          length=100.0, multi=False):
    a = [[-80.25, 43.54], [-80.249, 43.54]]
    geom = ({"type": "MultiLineString", "coordinates": [a, a]} if multi
            else {"type": "LineString", "coordinates": a})
    return {"type": "Feature", "geometry": geom,
            "properties": {"BIKEFACILITYID": fid, "STATUS": status,
                           "FACILITYTYPE": ftype, "ONROAD": "Yes",
                           "INSTALLYEAR": year, "Shape__Length": length}}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SLIM_PATH", str(tmp_path / "slim.geojsonl"))
    monkeypatch.setattr(config, "COUNT_PATH", str(tmp_path / "count.json"))
    monkeypatch.setattr(slim_mod, "MIN_EXPECTED", 2)
    monkeypatch.setattr(slim_mod, "MAX_EXPECTED", 10)
    return tmp_path


def _write_source(path, features):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def test_slim_writes_one_line_per_line_and_skips_the_rest(paths):
    src = paths / "src.geojson"
    _write_source(src, [
        _line(1, length=1200.4, year=2026),
        _line(2, "Planned", length=50, year=2026),
        _line(3, ftype="MUP", multi=True, length=300, year=2025),
        _line(4, ftype="Signed Route", length=500, year=2026),
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
         "properties": {}},
        {"type": "Feature", "geometry": None, "properties": {}},
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": []},
         "properties": {}},
    ])
    assert slim(str(src)) == config.SLIM_PATH
    with open(config.SLIM_PATH, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f]
    assert [l["properties"]["id"] for l in lines] == [1, 2, 3, 4]
    assert [l["properties"]["status"] for l in lines] == \
        ["in_service", "planned", "in_service", "in_service"]
    assert lines[2]["geometry"]["type"] == "MultiLineString"
    # Plain floats, not ijson's Decimals.
    assert lines[0]["geometry"]["coordinates"] == [[-80.25, 43.54], [-80.249, 43.54]]
    with open(config.COUNT_PATH, encoding="utf-8") as f:
        counts = json.load(f)
    # In service only: the planned row is in the file but not in the counts.
    assert counts == {"lines": 4, "in_service": 3, "in_service_km": 2.0,
                      "kinds": {"painted": 1, "mup": 1, "route": 1},
                      "kind_km": {"painted": 1.2, "mup": 0.3, "route": 0.5},
                      "latest_year": 2026, "latest_year_rows": 2}


def test_an_implausible_count_aborts(paths):
    src = paths / "src.geojson"
    _write_source(src, [_line(1)])
    with pytest.raises(RuntimeError, match="outside the expected range"):
        slim(str(src))
