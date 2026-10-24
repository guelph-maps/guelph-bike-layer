"""Configuration constants for the Guelph bike facilities tile layer build.

Single source of truth. No logic here.

Cloned from guelph-sidewalks-layer, the family's first line layer: the same
pipeline (download -> slim -> compare -> vector + raster -> site -> publish),
pointed at the City of Guelph Bike Facilities layer. What changes is what a
match means. A painted lane is not a line of its own in OSM but a tag on the
road beside it, on one side, so the comparison reads the road's cycleway tag
for the side the City line lies on. Off-road paths are matched as lines, and
signed routes against OSM's bicycle route relations.
"""

import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
SITE_DIR = os.path.join(BUILD_DIR, "site")
ASSETS_DIR = os.path.join(PROJECT_DIR, "assets")
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")

MBTILES_PATH = os.path.join(BUILD_DIR, "bike.mbtiles")
SLIM_PATH = os.path.join(DATA_DIR, "bike-slim.geojsonl")
COUNT_PATH = os.path.join(DATA_DIR, "bike.count.json")
LAST_DOWNLOAD_PATH = os.path.join(DATA_DIR, ".last-download.json")
# Downloaded files are named f"{DOWNLOAD_PREFIX}{date}.geojson".
DOWNLOAD_PREFIX = "bike-"

VECTOR_TILE_DIR = os.path.join(SITE_DIR, "tiles", "vector")
RASTER_TILE_DIR = os.path.join(SITE_DIR, "tiles", "raster")

# Data source: City of Guelph Bike Facilities (OpenData2 layer 1), 1,514 lines
# on 2026-10-24. maxRecordCount is 1,000, so the download pages through it.
# The service stores geometry in EPSG:26917, so outSR=4326 is not optional.
FEATURE_SERVER = (
    "https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData2"
    "/FeatureServer/1"
)
QUERY_URL = f"{FEATURE_SERVER}/query"
PAGE_SIZE = 1000
DATASET_PAGE = FEATURE_SERVER
# This layer REDISTRIBUTES City data as published tiles, and the licence
# attaches a required attribution to that. It is carried on every page. See
# the README section "Licence"; it is a condition, not a courtesy.
LICENSE_URL = "https://gismaps.guelph.ca/Images/OpenDataLicenceVersion2.pdf"
LICENSE_NOTICE = (
    "Contains information licensed under the Open Government Licence "
    "– City of Guelph."
)
# Plain-ASCII attribution embedded in tile metadata (it is passed through a
# shell, where the en dash in LICENSE_NOTICE is not safe).
ATTRIBUTION = (
    "Contains information licensed under the Open Government Licence "
    "- City of Guelph"
)

# GitHub Pages target. PAGES_URL carries NO trailing slash: every tile URL on
# the site is built as f"{PAGES_URL}/tiles/...", and that string is the one
# thing on the page a reader copies verbatim into their editor.
GITHUB_REPO = "guelph-maps/guelph-bike-layer"
PAGES_URL = "https://guelph-maps.github.io/guelph-bike-layer"

# WSL distro that has tippecanoe installed (see wsl-setup.md). Used on Windows
# only; elsewhere tippecanoe is run directly.
WSL_DISTRO = "Ubuntu"

# Vector tiles. iD requests tiles at (map zoom - 1) and does NOT overzoom, so
# tiles must be generated natively through the zooms used for mapping.
VECTOR_MINZOOM = 14
VECTOR_MAXZOOM = 19
VECTOR_LAYER_NAME = "bike"

# Raster tiles. z14 shows the network a neighbourhood at a time; by z17 the
# two lanes of a street (4-10 m either side of its centreline) are separate
# strokes. Editors overzoom z17 further.
RASTER_ZOOMS = [14, 15, 16, 17]

# Source property keys read from the Bike Facilities GeoJSON.
ID_KEY = "BIKEFACILITYID"    # the City's facility id; rises with each new row
STATUS_KEY = "STATUS"        # In Service / Planned / Out of Service
TYPE_KEY = "FACILITYTYPE"    # Bike Lane, MUP, Signed Route, Cycle Track, ...
ONROAD_KEY = "ONROAD"        # Yes / No
BUFFER_KEY = "BUFFERTYPE"    # None, Painted, Curbed, Barrier and Bollard, ...
YEAR_KEY = "INSTALLYEAR"     # a plain integer year, on every row
WIDTH_KEY = "FACILITYWIDTH"  # metres
SIGNED_KEY = "SIGNED"        # Yes / No
STREET_KEY = "STREETNAME"

IN_SERVICE = "In Service"
PLANNED = "Planned"

# What each City row is, for drawing and for matching. Derived in slim.py
# from FACILITYTYPE and BUFFERTYPE:
#   painted    a lane with no physical buffer
#   buffered   a painted buffer or rumble strip between lane and traffic
#   separated  a cycle track, or a lane behind a curb, bollards or a barrier
#   mup        an off-road multi-use path
#   route      a signed route on a shared road
#   spot       a crossride, intersection treatment or curb cut -- no settled
#              OSM tag, so shown and never counted
SPOT_TYPES = ("Crossride", "Bike Lane - Intersection", "Left-Turn Curb Cut",
              "Other")
LANE_TYPES = ("Bike Lane", "Bike Lane - Green", "Contraflow", "Cycle Track")
SEPARATED_BUFFERS = ("Curbed", "Rolled Curb", "Barrier", "Bollard",
                     "Barrier and Bollard")
PAINTED_BUFFERS = ("Painted", "Rumble Strip")

# --- OSM comparison (gap-review page) ---
# Every City line is sampled every SAMPLE_STEP_M metres, and each sample asks
# what OSM has beside it. compare.py's docstring has the rule in full.
SAMPLE_STEP_M = 5.0
# On-road lanes: the City draws a lane line 4-10 m off the road centreline
# (p95 9.5 m in the recalibration), so the road that carries its tag is the
# nearest within ROAD_M. Closer than SIDE_MIN_M, the side cannot be read.
ROAD_M = 20.0
SIDE_MIN_M = 1.5
# A separately mapped cycleway within this far stands in for a road tag.
BIKEWAY_M = 12.0
# Off-road paths and cycle tracks: any path-like OSM way within this far.
PATH_M = 15.0
# Signed routes: a member way of a route=bicycle relation within this far.
ROUTE_M = 15.0
# At an intersection the nearest road can be the cross street. A candidate
# only counts when its direction agrees with the City line's within this many
# degrees; with none agreeing, the sample has no road.
BEARING_MAX_DEG = 30.0
# Segment bands, length-weighted: covered >= MATCHED_SHARE is in OSM.
MATCHED_SHARE = 0.70
# Shorter than this (untraced metres for a gap, length for nosep / nobike),
# a segment is not listed. The City cuts protected intersections into 5-15 m
# corner pieces, and a corner's nearest road is the cross street whichever
# way it points.
MIN_LISTED_M = 15.0
# A matched lane with a physical City buffer is "nosep" when at least this
# share of its matched length has no separation/buffer tag on its side.
NOSEP_SHARE = 0.5
# Listed segments are named after the nearest named OSM road within this far
# (the City's own STREETNAME is the fallback).
STREET_M = 40.0
# "new": a gap whose City install year is this recent (current year minus
# NEW_YEARS or later). INSTALLYEAR is a year, not a date, so "installed in
# the last twelve months" can only be read as this year or last.
NEW_YEARS = 1

# OSM highway values read as roads that can carry a lane tag. Service roads
# are left out: a parking aisle beside an arterial would otherwise be the
# "nearest road" for the lane on that side.
ROAD_HIGHWAYS = (
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "living_street", "road", "busway",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
    "tertiary_link",
)
PATH_HIGHWAYS = (
    "footway", "path", "cycleway", "pedestrian", "steps", "track",
    "bridleway", "corridor",
)

# The mirror list is the parks layer's, for the parks layer's reasons:
# overpass.kumi.systems and overpass.private.coffee have both been caught
# serving months-stale data, which looks exactly like success (private.coffee
# answered the recalibration with a 2026-05-31 base). OSM_MAX_AGE_DAYS refuses
# such a reply from any mirror: the gap page asserts timestamp_osm_base, not
# merely that the request came back.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
OVERPASS_TIMEOUT = 600
OVERPASS_ROUNDS = 3
OVERPASS_ROUND_WAIT = 60
# Floor on a reply's element count. A regional instance answers an
# out-of-region bbox with a valid EMPTY result, and taking that at face value
# reports every City facility as missing from OSM. About half the first live
# reply: 18,099 elements from overpass-api.de on 2026-10-24.
OSM_MIN_ELEMENTS = 9000
# And on its bicycle route relations, which every signed route is matched
# against: 17 on 2026-10-24. A reply without them would report every signed
# route as unsigned.
OSM_MIN_ROUTES = 8
OSM_MAX_AGE_DAYS = 3
# Overpass rejects the default requests User-Agent (HTTP 406); identify the tool.
USER_AGENT = "guelph-bike-layer/0.1 (toronto@comentality.com)"
# Guelph bounding box (S, W, N, E), verbatim from guelph-beholder's config.toml
# -- a touch larger than the city. OSM ways outside the city simply match
# nothing, so a loose box is harmless.
GUELPH_BBOX = (43.46, -80.34, 43.60, -80.14)
# Guelph city centre; where the preview and gap maps open.
GUELPH_CENTER = (43.5448, -80.2482)
# UTM zone 17N: the metric frame the matching runs in.
METRIC_EPSG = 32617
OSM_CACHE_PATH = os.path.join(DATA_DIR, "osm-ways.json")
# When the cached Overpass reply was fetched, from where, and the OSM database
# timestamp the reply declares about itself.
OSM_FETCH_PATH = os.path.join(DATA_DIR, ".osm-fetch.json")
GAPS_GEOJSON_PATH = os.path.join(DATA_DIR, "gaps.geojson")
GAPS_COUNT_PATH = os.path.join(DATA_DIR, "gaps.count.json")

# --- Gap history (trend page) ---
# One JSON line per live compare run. It lives in data/ like the rest of the
# observer's state; its published copy re-seeds a checkout that has none.
HISTORY_PATH = os.path.join(DATA_DIR, "history.jsonl")
HISTORY_URL = f"{PAGES_URL}/gaps/history.jsonl"
