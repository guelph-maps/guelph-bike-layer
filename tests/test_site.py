import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, site  # noqa: E402


def test_gap_page_renders_legacy_route_migration_count_and_filter(
        tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    data_dir.mkdir()
    (data_dir / "gaps.geojson").write_text(
        '{"type":"FeatureCollection","features":[]}', encoding="utf-8"
    )
    (data_dir / "gaps.count.json").write_text(
        json.dumps({"legacy_route": 3}), encoding="utf-8"
    )
    monkeypatch.setattr(config, "GAPS_GEOJSON_PATH", str(data_dir / "gaps.geojson"))
    monkeypatch.setattr(config, "GAPS_COUNT_PATH", str(data_dir / "gaps.count.json"))
    monkeypatch.setattr(config, "SITE_DIR", str(site_dir))
    monkeypatch.setattr(site, "_build_history_page", lambda *_args: None)

    site._build_gaps_page("2026-11-19")

    html = (site_dir / "gaps" / "index.html").read_text(encoding="utf-8")
    assert "<strong>3</strong><span>legacy route migration</span>" in html
    assert 'id="show-legacy_route"' in html
