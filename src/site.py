"""Render the GitHub Pages landing page into the build output."""

import json
import os
import re
import shutil
from datetime import date

from PIL import Image

from src import config, history

# Screenshots shown on the landing page, copied from the project root when
# present (they are added manually after the first publish).
SCREENSHOTS = ["iD.png", "JOSM.png"]
SCREENSHOT_MAX_WIDTH = 1500


def build_site():
    """Render index.html, copy assets and screenshots into build/site/."""
    os.makedirs(config.SITE_DIR, exist_ok=True)

    # data/bike.count.json is written by slim; before the first slim the page
    # still renders, with the figures from the 2026-10-24 download.
    counts = _load_json(config.COUNT_PATH)
    summary = _load_json(config.GAPS_COUNT_PATH)
    kind_km = counts.get("kind_km", {})

    build_date = date.today().isoformat()

    with open(os.path.join(config.ASSETS_DIR, "index.html.tmpl"),
              encoding="utf-8") as f:
        html = f.read()

    replacements = {
        "{{PAGES_URL}}": config.PAGES_URL,
        "{{VECTOR_URL}}": f"{config.PAGES_URL}/tiles/vector/{{z}}/{{x}}/{{y}}.pbf",
        "{{RASTER_URL}}": f"{config.PAGES_URL}/tiles/raster/{{z}}/{{x}}/{{y}}.png",
        "{{RASTER_URL_JOSM}}": (
            f"{config.PAGES_URL}/tiles/raster/{{zoom}}/{{x}}/{{y}}.png"
        ),
        "{{VECTOR_URL_JOSM}}": (
            f"{config.PAGES_URL}/tiles/vector/{{zoom}}/{{x}}/{{y}}.pbf"
        ),
        "{{BUILD_DATE}}": build_date,
        "{{DATA_DATE}}": _data_date(build_date),
        "{{LINE_COUNT}}": f"{counts.get('lines', 1514):,}",
        "{{IN_SERVICE_KM}}": f"{counts.get('in_service_km', 209.1):,}",
        "{{LATEST_YEAR}}": str(counts.get("latest_year") or 2026),
        "{{LATEST_YEAR_ROWS}}": f"{counts.get('latest_year_rows', 61):,}",
        **{"{{KM_" + k.upper() + "}}": f"{kind_km.get(k, 0):,}"
           for k in ("painted", "buffered", "separated", "mup", "route", "spot")},
        # The landing page links to the gap page by its headline figure; with
        # no comparison yet there is no figure, and the link says so instead.
        "{{WORK_COUNT}}": f"{summary['work']:,}" if "work" in summary else "?",
        "{{NEW_COUNT}}": f"{summary.get('new', 0):,}",
        "{{RASTER_MINZOOM}}": str(min(config.RASTER_ZOOMS)),
        "{{RASTER_MAXZOOM}}": str(max(config.RASTER_ZOOMS)),
        "{{VECTOR_MINZOOM}}": str(config.VECTOR_MINZOOM),
        "{{VECTOR_MAXZOOM}}": str(config.VECTOR_MAXZOOM),
        "{{VECTOR_LAYER_NAME}}": config.VECTOR_LAYER_NAME,
        "{{GITHUB_REPO}}": config.GITHUB_REPO,
        "{{DATASET_PAGE}}": config.DATASET_PAGE,
        "{{LICENSE_URL}}": config.LICENSE_URL,
        "{{LICENSE_NOTICE}}": config.LICENSE_NOTICE,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    with open(os.path.join(config.SITE_DIR, "index.html"), "w",
              encoding="utf-8") as f:
        f.write(html)
    for name in ("index.css", "index.js"):
        shutil.copy(
            os.path.join(config.ASSETS_DIR, name),
            os.path.join(config.SITE_DIR, name),
        )
    for name in SCREENSHOTS:
        src = os.path.join(config.PROJECT_DIR, name)
        if os.path.isfile(src):
            _copy_image(src, os.path.join(config.SITE_DIR, name),
                        SCREENSHOT_MAX_WIDTH)
    _build_gaps_page(build_date)
    # .nojekyll stops GitHub Pages running Jekyll over the tile directories.
    open(os.path.join(config.SITE_DIR, ".nojekyll"), "w").close()
    print(f"Site rendered: {config.SITE_DIR}")


def _build_gaps_page(build_date):
    """Render gaps/ (map + table) when a comparison has produced gaps.geojson."""
    if not os.path.isfile(config.GAPS_GEOJSON_PATH):
        print("  (no gaps.geojson -- run 'compare'; skipping gap page)")
        return

    gaps_dir = os.path.join(config.SITE_DIR, "gaps")
    os.makedirs(gaps_dir, exist_ok=True)

    summary = _load_json(config.GAPS_COUNT_PATH)

    with open(os.path.join(config.ASSETS_DIR, "gaps.html.tmpl"),
              encoding="utf-8") as f:
        html = f.read()
    replacements = {
        "{{PAGES_URL}}": config.PAGES_URL,
        "{{BUILD_DATE}}": build_date,
        "{{DATA_DATE}}": _data_date(build_date),
        "{{NEW_COUNT}}": f"{summary.get('new', 0):,}",
        "{{MISSING_COUNT}}": f"{summary.get('missing', 0):,}",
        "{{SAYS_NO_COUNT}}": f"{summary.get('says_no', 0):,}",
        "{{NOSEP_COUNT}}": f"{summary.get('nosep', 0):,}",
        "{{NOBIKE_COUNT}}": f"{summary.get('nobike', 0):,}",
        "{{UNSIGNED_COUNT}}": f"{summary.get('unsigned_route', 0):,}",
        "{{PLANNED_COUNT}}": f"{summary.get('planned', 0):,}",
        "{{SPOT_COUNT}}": f"{summary.get('spot', 0):,}",
        **{"{{" + k.upper() + "}}": f"{summary.get(k, 0):,}"
           for k in ("lane_km", "lane_pos_km", "lane_any_km", "buffer_km",
                     "sep_ok_km", "recent_km", "recent_gap_km")},
        "{{RECENT_SINCE}}": str(summary.get("recent_since", "")),
        "{{RASTER_MINZOOM}}": str(min(config.RASTER_ZOOMS)),
        "{{RASTER_MAXZOOM}}": str(max(config.RASTER_ZOOMS)),
        "{{OSM_DATE}}": summary.get("osm_date", build_date),
        "{{OSM_NOTE}}": _osm_note(summary),
        "{{GITHUB_REPO}}": config.GITHUB_REPO,
        # The gap page is published separately from the landing page and is
        # often the only page a mapper opens, so it carries the City licence
        # notice in its own right. Both pages must show it: publishing these
        # tiles is a redistribution, and the notice is the licence condition
        # attached to that, not a footer nicety.
        "{{LICENSE_URL}}": config.LICENSE_URL,
        "{{LICENSE_NOTICE}}": config.LICENSE_NOTICE,
        "{{DATASET_PAGE}}": config.DATASET_PAGE,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)

    with open(os.path.join(gaps_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy(config.GAPS_GEOJSON_PATH, os.path.join(gaps_dir, "gaps.geojson"))
    for name in ("gaps.css", "gaps.js"):
        shutil.copy(os.path.join(config.ASSETS_DIR, name),
                    os.path.join(gaps_dir, name))
    print(f"Gap page rendered: {gaps_dir}")
    _build_history_page(gaps_dir, build_date)


def _build_history_page(gaps_dir, build_date):
    """Render gaps/history.html: every recorded run's gap counts, charted.

    The rows are inlined into the page (the chart needs no second request) and
    published beside it as history.jsonl, which is both the raw data for anyone
    who wants it and what re-seeds a checkout without a history file.
    """
    rows = history.load()
    with open(os.path.join(config.ASSETS_DIR, "history.html.tmpl"),
              encoding="utf-8") as f:
        html = f.read()
    replacements = {
        "{{PAGES_URL}}": config.PAGES_URL,
        "{{BUILD_DATE}}": build_date,
        "{{GITHUB_REPO}}": config.GITHUB_REPO,
        "{{RUN_COUNT}}": f"{len(rows):,}",
        "{{FIRST_DATE}}": rows[0]["date"] if rows else build_date,
        "{{RECENT_SINCE}}": str(
            _load_json(config.GAPS_COUNT_PATH).get("recent_since", "")),
        "{{HISTORY_JSON}}": json.dumps(rows),
        "{{HISTORY_ROWS}}": "\n".join(_history_row(r) for r in reversed(rows)),
        # Only counts, but counts of the City's facilities, and like the gap page
        # this can be the one page a reader opens: it carries the notice too.
        "{{LICENSE_URL}}": config.LICENSE_URL,
        "{{LICENSE_NOTICE}}": config.LICENSE_NOTICE,
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    with open(os.path.join(gaps_dir, "history.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy(os.path.join(config.ASSETS_DIR, "history.js"),
                os.path.join(gaps_dir, "history.js"))
    if os.path.isfile(config.HISTORY_PATH):
        shutil.copy(config.HISTORY_PATH, os.path.join(gaps_dir, "history.jsonl"))
    print(f"History page rendered: {len(rows):,} runs")


def _history_row(r):
    source = "reconstructed" if r.get("source") == "attic" else "live"
    cells = [r["date"]] + [f"{r.get(k, 0):,}" for k in history.FIELDS] + [source]
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _osm_note(summary):
    """Warn on the page itself when the OSM half of the diff is not current.

    The gap list is only worth acting on if both sides are fresh, and the OSM
    side is the one that moves daily. A page dated today whose OSM data is two
    weeks old sends a mapper to add a lane somebody else already added.
    """
    if not summary.get("osm_stale"):
        return ""
    when = summary.get("osm_date", "an earlier run")
    return (
        '<p class="stale">Overpass could not be reached for this build, so '
        f'these gaps were computed against OSM data from <strong>{when}</strong>. '
        'Anything mapped since then still shows as a gap.</p>'
    )


def _load_json(path):
    """A JSON file's contents, or {} when the step that writes it has not run."""
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _data_date(fallback):
    """Return the City data's date (YYYY-MM-DD) from the download sidecar."""
    if os.path.isfile(config.LAST_DOWNLOAD_PATH):
        with open(config.LAST_DOWNLOAD_PATH, encoding="utf-8") as f:
            sidecar = json.load(f)
        match = re.search(r"\d{4}-\d{2}-\d{2}", sidecar.get("filename", ""))
        if match:
            return match.group(0)
    return fallback


def _copy_image(src, dst, max_width):
    """Copy an image into the site, downscaling it if wider than max_width."""
    with Image.open(src) as img:
        if img.width > max_width:
            height = round(img.height * max_width / img.width)
            resized = img.resize((max_width, height), Image.LANCZOS)
            resized.save(dst, optimize=True)
            print(f"  {os.path.basename(src)}: {img.width}px -> {max_width}px")
        else:
            shutil.copy(src, dst)
