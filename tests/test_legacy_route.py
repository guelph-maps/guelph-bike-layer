import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import compare, config  # noqa: E402


def _el(eid, tags):
    pts = [{"lat": 43.54, "lon": -80.25 + i * 0.001} for i in range(2)]
    return {"type": "way", "id": eid, "tags": tags, "geometry": pts}


def test_legacy_lcn_route_is_emitted_as_a_separate_migration_row():
    points = [(-80.25, 43.54), (-80.249, 43.54)]
    city = [{
        "props": {"id": 18, "status": "in_service", "type": "Signed Route",
                  "kind": "route", "year": 2020, "street": "Emma Street",
                  "length": 80},
        "geom": {"type": "LineString", "coordinates": points},
        "lines": [compare._line(points)],
    }]
    osm = compare._osm_ways({"elements": [
        _el(43, {"highway": "secondary", "name": "Emma Street", "lcn": "yes"})
    ]})

    rows = compare._legacy_route_migration_rows(city, osm)

    assert len(rows) == 1
    assert rows[0]["properties"]["id"] == 18
    assert rows[0]["properties"]["status"] == "legacy_route"
    assert rows[0]["properties"]["way"] == 43


def test_compare_includes_legacy_routes_in_gap_geojson_and_summary(
        tmp_path, monkeypatch):
    legacy = {"type": "Feature", "properties": {"status": "legacy_route"}}
    summary = {
        **dict.fromkeys(compare.STATUSES, 0),
        "lane_pos_km": 0, "lane_km": 0, "lane_bikeway_km": 0,
        "lane_absent_km": 0, "lane_no_km": 0, "lane_any_km": 0,
        "sep_ok_km": 0, "buffer_km": 0, "path_missing_km": 0,
        "nobike_km": 0, "path_km": 0, "unsigned_km": 0, "route_km": 0,
        "recent_since": 2026, "recent_gap_km": 0, "recent_km": 0,
    }
    written = {}
    monkeypatch.setattr(compare, "_load_osm", lambda: ({}, "2026-11-04", False))
    monkeypatch.setattr(compare, "_osm_ways", lambda _data: {
        "road": [], "path": [], "bikeway": [], "route": [],
    })
    monkeypatch.setattr(compare, "_city_features", lambda: iter(()))
    monkeypatch.setattr(compare, "match", lambda _city, _osm: ([], summary))
    monkeypatch.setattr(compare, "_legacy_route_migration_rows",
                        lambda _city, _osm: [legacy])
    monkeypatch.setattr(compare, "_write_gaps",
                        lambda features: written.setdefault("gaps", features))
    monkeypatch.setattr(config, "GAPS_COUNT_PATH", str(tmp_path / "summary.json"))
    monkeypatch.setattr(compare.history, "record", lambda _summary: None)

    compare.compare()

    assert written["gaps"] == [legacy]
    with open(config.GAPS_COUNT_PATH, encoding="utf-8") as f:
        assert json.load(f)["legacy_route"] == 1
