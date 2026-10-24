"""Render the City's bike facilities into raster (PNG) map tiles using Pillow.

Pure Python -- no native dependencies, runs the same on Windows and Linux.

The sidewalks layer's renderer, coloured by what each facility is on the
ground (slim.py's "kind"), so a mapper reads the tag to add off the colour:

  painted    blue           cycleway:<side>=lane
  buffered   violet         ... + :buffer / :separation=rumble_strip
  separated  green          =track, or a lane behind a curb or bollards
  mup        orange         highway=path + bicycle=designated
  route      amber, dashed  a signed route on a shared street
  spot       pink, wide     crossrides, intersection treatments, curb cuts
  planned    grey, dashed   not built yet

Out of Service rows are not drawn.
"""

import json
import math
import os
from collections import defaultdict

from PIL import Image, ImageDraw

from src import config
from src.tilemath import TILE_SIZE, lonlat_to_pixel

# kind -> (colour, dashed). Drawn in this order, so the bottom of the list
# ends up on top: a signed route under the lane that shares its street, a
# crossride over both.
STYLES = {
    "route": ((245, 159, 0, 255), True),       # #f59f00
    "planned": ((134, 142, 150, 255), True),   # #868e96
    "mup": ((232, 89, 12, 255), False),        # #e8590c
    "painted": ((28, 126, 214, 255), False),   # #1c7ed6
    "buffered": ((112, 72, 232, 255), False),  # #7048e8
    "separated": ((43, 138, 62, 255), False),  # #2b8a3e
    "spot": ((214, 51, 108, 255), False),      # #d6336c
}
ORDER = {k: i for i, k in enumerate(STYLES)}
CLEAR = (0, 0, 0, 0)

# Stroke width by zoom. At z14 a street's two lanes are a pixel apart, so the
# stroke is a marker of "there is a facility here"; from z16 the lanes part
# and a wider stroke reads over roof and tree texture.
WIDE_STROKE_MIN_ZOOM = 16
# Dash pattern for routes and planned rows, in pixels: on, off.
DASH = (8, 5)


def build_raster(slim_path=None):
    """Render PNG tiles for every zoom in config.RASTER_ZOOMS.

    Returns a dict {zoom: tile_count}.
    """
    slim_path = slim_path or config.SLIM_PATH
    lines = _read_lines(slim_path)
    return {z: _render_zoom(lines, z) for z in config.RASTER_ZOOMS}


def style_key(props):
    """Which STYLES entry draws a facility, or None to leave it out."""
    status = props.get("status")
    if status == "planned":
        return "planned"
    if status != "in_service":
        return None
    return props.get("kind") if props.get("kind") in STYLES else "painted"


def _read_lines(slim_path):
    """Return [(style, [(lon, lat), ...]), ...]: one entry per line part."""
    lines = []
    with open(slim_path, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            key = style_key(feat["properties"])
            if key is None:
                continue
            geom = feat["geometry"]
            parts = (geom["coordinates"] if geom["type"] == "MultiLineString"
                     else [geom["coordinates"]])
            for part in parts:
                if len(part) >= 2:
                    lines.append((key, part))
    lines.sort(key=lambda item: ORDER[item[0]])
    return lines


def _render_zoom(lines, zoom):
    print(f"Raster z{zoom}: bucketing {len(lines):,} lines into tiles ...")
    base = 3 if zoom >= WIDE_STROKE_MIN_ZOOM else 2
    tiles = defaultdict(list)
    for key, part in lines:
        colour, dashed = STYLES[key]
        width = base + 2 if key == "spot" else base
        projected = [lonlat_to_pixel(lon, lat, zoom) for lon, lat in part]
        pieces = dashes(projected, *DASH) if dashed else [projected]
        for piece in pieces:
            xs = [p[0] for p in piece]
            ys = [p[1] for p in piece]
            for tkey in _tiles_touching((min(xs), min(ys), max(xs), max(ys)), width):
                tiles[tkey].append((colour, width, piece))

    out_dir = os.path.join(config.RASTER_TILE_DIR, str(zoom))
    print(f"Raster z{zoom}: rendering {len(tiles):,} tiles ...")
    made_dirs = set()
    written = 0
    for (tx, ty), parts in tiles.items():
        img = _render_tile(tx, ty, parts)
        if img.getbbox() is None:
            continue  # bbox over-approximation: the line never entered this tile
        tdir = os.path.join(out_dir, str(tx))
        if tdir not in made_dirs:
            os.makedirs(tdir, exist_ok=True)
            made_dirs.add(tdir)
        img.save(os.path.join(tdir, f"{ty}.png"), optimize=True)
        written += 1
    return written


def dashes(pts, on, off):
    """Cut a pixel polyline into dash pieces of ``on`` px every ``on + off``.

    Worked in global pixels from the line's own start, so a dash that crosses
    a tile edge is cut identically in both tiles.
    """
    pieces = []
    period = on + off
    walked = 0.0          # distance along the line at pts[k - 1]
    current = None        # the dash being drawn, or None in a gap
    for k in range(1, len(pts)):
        (x0, y0), (x1, y1) = pts[k - 1], pts[k]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg == 0:
            continue
        t = 0.0
        while t < seg:
            phase = (walked + t) % period
            if phase < on:
                step = min(on - phase, seg - t)
                if current is None:
                    current = [_lerp(x0, y0, x1, y1, t / seg)]
                current.append(_lerp(x0, y0, x1, y1, (t + step) / seg))
                if phase + step >= on - 1e-9:
                    pieces.append(current)
                    current = None
            else:
                step = min(period - phase, seg - t)
            t += step
        walked += seg
    if current is not None and len(current) >= 2:
        pieces.append(current)
    return pieces


def _lerp(x0, y0, x1, y1, f):
    return (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)


def _tiles_touching(bbox, pad):
    x0, y0, x1, y1 = bbox
    for tx in range(int((x0 - pad) // TILE_SIZE), int((x1 + pad) // TILE_SIZE) + 1):
        for ty in range(int((y0 - pad) // TILE_SIZE), int((y1 + pad) // TILE_SIZE) + 1):
            yield (tx, ty)


def _render_tile(tx, ty, parts):
    img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), CLEAR)
    draw = ImageDraw.Draw(img)
    ox, oy = tx * TILE_SIZE, ty * TILE_SIZE
    # Parts arrive in STYLES order (the lines were sorted before bucketing).
    for colour, width, pts in parts:
        draw.line([(x - ox, y - oy) for x, y in pts], fill=colour,
                  width=width, joint="curve")
    return img
