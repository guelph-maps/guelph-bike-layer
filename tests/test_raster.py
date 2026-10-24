"""Tests for the raster tile renderer: colour by kind, dashes, tile edges."""

import json
import math
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config  # noqa: E402
from src.raster import (  # noqa: E402
    CLEAR, DASH, STYLES, _render_tile, _tiles_touching, build_raster, dashes,
    style_key,
)
from src.tilemath import TILE_SIZE, pixel_in_tile  # noqa: E402

LAT = 43.5448
# One horizontal line per kind, 0.001 deg (~110 m) apart.
KINDS = ("painted", "buffered", "separated", "mup", "spot")


def _colour(key):
    return STYLES[key][0]


def _feature(coords, **props):
    geom = ({"type": "MultiLineString", "coordinates": coords}
            if isinstance(coords[0][0], list) else
            {"type": "LineString", "coordinates": coords})
    return {"type": "Feature", "geometry": geom,
            "properties": {"status": "in_service", **props}}


@pytest.fixture
def tiles(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RASTER_TILE_DIR", str(tmp_path / "raster"))
    monkeypatch.setattr(config, "RASTER_ZOOMS", [14, 17])
    slim_path = tmp_path / "slim.geojsonl"
    feats = [_feature([[-80.2490, LAT + k * 0.001], [-80.2470, LAT + k * 0.001]],
                      kind=kind) for k, kind in enumerate(KINDS)]
    feats.append(_feature([[-80.2490, LAT - 0.001], [-80.2470, LAT - 0.001]],
                          kind="painted", status="out_of_service"))
    # A MultiLineString part and a degenerate one-point part.
    feats.append(_feature([[[-80.2490, LAT - 0.002], [-80.2470, LAT - 0.002]],
                           [[-80.2480, LAT - 0.003]]], kind="separated"))
    with open(slim_path, "w", encoding="utf-8") as f:
        for feat in feats:
            f.write(json.dumps(feat) + "\n")
    return tmp_path, str(slim_path)


def _pixel(root, lon, lat, zoom):
    tx, ty, ox, oy = pixel_in_tile(lon, lat, zoom)
    path = root / "raster" / str(zoom) / str(tx) / f"{ty}.png"
    if not path.is_file():
        return CLEAR
    with Image.open(path) as img:
        return img.convert("RGBA").getpixel((int(ox), int(oy)))


def test_tiles_are_written_for_every_zoom(tiles):
    root, slim_path = tiles
    counts = build_raster(slim_path)
    assert set(counts) == {14, 17}
    assert all(n > 0 for n in counts.values())
    for z, n in counts.items():
        assert len(list((root / "raster" / str(z)).rglob("*.png"))) == n


@pytest.mark.parametrize("k, kind", list(enumerate(KINDS)))
def test_each_kind_is_drawn_in_its_colour(tiles, k, kind):
    root, slim_path = tiles
    build_raster(slim_path)
    assert _pixel(root, -80.2480, LAT + k * 0.001, 17) == _colour(kind)


def test_out_of_service_is_not_drawn(tiles):
    root, slim_path = tiles
    build_raster(slim_path)
    assert _pixel(root, -80.2480, LAT - 0.001, 17) == CLEAR


def test_every_part_of_a_multiline_is_drawn(tiles):
    root, slim_path = tiles
    build_raster(slim_path)
    assert _pixel(root, -80.2480, LAT - 0.002, 17) == _colour("separated")


def test_off_the_line_is_clear(tiles):
    root, slim_path = tiles
    build_raster(slim_path)
    # ~33 m north of the painted line at z17: well clear of a 3 px stroke.
    assert _pixel(root, -80.2480, LAT + 0.0003, 17) == CLEAR


@pytest.mark.parametrize("props, key", [
    ({"status": "in_service", "kind": "mup"}, "mup"),
    ({"status": "in_service", "kind": "route"}, "route"),
    ({"status": "planned", "kind": "painted"}, "planned"),
    ({"status": "out_of_service", "kind": "painted"}, None),
    ({"status": "in_service"}, "painted"),
])
def test_style_key(props, key):
    assert style_key(props) == key


def test_routes_and_planned_rows_are_dashed():
    assert STYLES["route"][1] and STYLES["planned"][1]
    assert not any(STYLES[k][1] for k in KINDS)


def test_dashes_cut_a_line_into_on_off_pieces():
    on, off = DASH
    pieces = dashes([(0, 0), (100, 0)], on, off)
    starts = [p[0][0] for p in pieces]
    assert starts == [k * (on + off) for k in range(len(starts))]
    assert all(abs((p[-1][0] - p[0][0]) - on) < 1e-9 for p in pieces[:-1])
    # Every dash lies on the line.
    assert all(y == 0 for p in pieces for _x, y in p)


def test_a_dash_carries_round_a_corner():
    # 5 px along x, then on up y: the first dash bends with the line.
    pieces = dashes([(0, 0), (5, 0), (5, 20)], 8, 5)
    assert pieces[0] == [(0.0, 0.0), (5.0, 0.0), (5.0, 3.0)]


def test_dashes_are_the_same_whichever_tile_draws_them():
    # Phase runs from the line's own start in global pixels, so two tiles
    # cutting the same line agree on where every dash is.
    line = [(250, 10), (270, 10)]
    assert dashes(line, 8, 5) == dashes(list(line), 8, 5)


def test_the_later_style_is_drawn_on_top():
    under = (_colour("painted"), 3, [(10, 100), (200, 100)])
    over = (_colour("spot"), 5, [(100, 100), (200, 100)])
    img = _render_tile(0, 0, [under, over])
    assert img.getpixel((150, 100)) == _colour("spot")
    assert img.getpixel((50, 100)) == _colour("painted")


def test_tile_coordinates_are_local():
    c = _colour("painted")
    a = _render_tile(0, 0, [(c, 2, [(10, 10), (60, 40)])])
    b = _render_tile(1, 1, [(c, 2, [(266, 266), (316, 296)])])
    assert a.tobytes() == b.tobytes()


def test_tiles_touching_includes_the_stroke_overhang():
    # A line ending exactly on a tile edge still paints its stroke there.
    assert set(_tiles_touching((10, 10, 256, 100), 1)) == {(0, 0), (1, 0)}
    assert set(_tiles_touching((10, 10, 200, 100), 1)) == {(0, 0)}


def _lonlat(px, py, zoom):
    """Global pixel -> lon/lat, the inverse of tilemath.lonlat_to_pixel."""
    scale = TILE_SIZE * 2 ** zoom
    lon = px / scale * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / scale))))
    return [lon, lat]


def test_a_tile_the_line_never_entered_is_not_written(tmp_path, monkeypatch):
    # The diagonal's bbox spans a 2 x 2 block of tiles, but it crosses the
    # vertical tile edge below the horizontal one, so it never enters the
    # top-right tile. That tile is rendered blank and must not be saved.
    monkeypatch.setattr(config, "RASTER_TILE_DIR", str(tmp_path / "raster"))
    monkeypatch.setattr(config, "RASTER_ZOOMS", [17])
    tx, ty, _ox, _oy = pixel_in_tile(-80.2480, LAT, 17)
    x0, y0 = tx * TILE_SIZE, ty * TILE_SIZE
    a = _lonlat(x0 + 200, y0 + 100, 17)
    b = _lonlat(x0 + 300, y0 + 400, 17)
    slim_path = tmp_path / "slim.geojsonl"
    slim_path.write_text(json.dumps(_feature([a, b], kind="painted")) + "\n")
    assert build_raster(str(slim_path)) == {17: 3}
    written = {(int(p.parent.name), int(p.stem))
               for p in (tmp_path / "raster" / "17").rglob("*.png")}
    assert written == {(tx, ty), (tx, ty + 1), (tx + 1, ty + 1)}
