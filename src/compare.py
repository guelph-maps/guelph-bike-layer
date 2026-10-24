"""Compare the City's bike facilities against OSM.

Pulls every road and path-like way in the Guelph bbox from Overpass, and
every route=bicycle relation with its member geometry, then walks each City
line in steps of config.SAMPLE_STEP_M and asks what OSM has beside each
sample. What counts depends on what the City line is:

On-road lanes (Bike Lane, Bike Lane - Green, Contraflow, an on-road Cycle
Track). OSM maps these as a tag on the road, on one side, so each sample:

  bikeway   a separately mapped cycleway (highway=cycleway, or a path with
            bicycle=designated) within BIKEWAY_M                   -- covered
  pos       the road within ROAD_M carries a positive cycleway value on the
            sample's side: cycleway:<side>, cycleway:both, or a plain
            cycleway=* (on a oneway road that plain tag is read as the right
            side only). Contraflow also accepts oneway:bicycle=no.  -- covered
  no        that side says cycleway=no / none
  absent    the road says nothing for that side
  noroad    no road within ROAD_M

The side is which side of the OSM way's direction the sample lies on, so the
tag a mapper adds is cycleway:left or :right of THAT way. A sample within
SIDE_MIN_M of the centreline has no readable side (3.0 km of City lane lines
were drawn on the centreline itself in the recalibration); it is judged "any
side" -- positive if any of the four keys is -- and its segment says so.

Roads and separate cycleways only count when their direction agrees with the
City line's (BEARING_MAX_DEG): at an intersection the nearest road is often
the cross street, whose tags say nothing about this lane.

Where the City records a buffer, a covered sample also asks whether OSM has
it: a separate cycleway, a cycleway:<side>:separation* or :buffer* key, or
(for a physical buffer) cycleway:<side>=track.

Off-road paths (MUP, an off-road Cycle Track): any path-like way within
PATH_M covers it, preferring one whose direction agrees. It is "nobike" when
that way is a footway (or pedestrian way, or steps) with no bicycle access
tag, or bicycle=no. A Cycle Track with no path beside it is also covered by a
positive cycleway tag on the road on its side.

Signed routes: covered by a member way of a route=bicycle relation within
ROUTE_M, a separate cycleway, or a road carrying any positive cycleway tag or
bicycle=designated.

Each City segment then gets one status, length-weighted:

  covered < MATCHED_SHARE   a gap: "says_no" (lanes, when most of the
                            uncovered length says no), "unsigned_route"
                            (signed routes), else "missing"; any of these
                            on a facility installed this year or last is
                            "new" instead, and keeps the underlying kind in
                            its "gap" property.
  covered, but              "nosep" -- a lane whose City buffer OSM does not
                            record on NOSEP_SHARE of its covered length;
                            "nobike" -- a path mostly matched to a footway
                            with no bicycle access.

A gap of under MIN_LISTED_M untraced metres, or a nosep / nobike segment
shorter than that, is not listed: those are the corner pieces of a protected
intersection, whose nearest road is the cross street whichever way they
point.

Not in service: a Planned row is "planned" (off by default) unless OSM has
it already; an Out of Service row is not listed. Crossrides, intersection
treatments and curb cuts have no settled OSM tag: every one is listed as
"spot", shown and never counted.

Only City -> OSM is compared: an OSM cycleway the City does not inventory
(campus, private sites) is not reported.

Every listed segment carries the tag to add ("tag") and the OSM way it is
about ("way"), and is named after the nearest named OSM road, with the City's
own STREETNAME as the fallback. Matching runs in UTM 17N metres with shapely's
STRtree; a flaky Overpass falls back to the cached reply, but only after every
mirror has been tried several times -- see _load_osm.
"""

import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import numpy as np
import requests
import shapely
from addressvault import net
from pyproj import Transformer

from src import config, history

# Order is the page's: work first, newest installs at the head of it.
STATUSES = ("new", "missing", "says_no", "nosep", "nobike", "unsigned_route",
            "planned", "spot")
# The statuses that are work a mapper can do, and so are counted.
WORK_STATUSES = ("new", "missing", "says_no", "nosep", "nobike",
                 "unsigned_route")
# Gap kinds a recent install turns into "new".
NEW_FROM = ("missing", "says_no", "unsigned_route")

POSITIVE = {"lane", "track", "shared_lane", "share_busway", "separate",
            "shoulder", "opposite_lane", "opposite_track", "opposite", "yes"}
NEGATIVE = {"no", "none"}
_CYCLEWAY_KEYS = ("cycleway", "cycleway:both", "cycleway:left",
                  "cycleway:right")
_BIKE_OK = {"yes", "designated", "permissive"}
_FOOT_ONLY = {"footway", "pedestrian", "steps", "corridor"}

# The OSM tag for the separation the City records, by BUFFERTYPE.
SEPARATION_TAG = {
    "Painted": "buffer=yes",
    "Rumble Strip": "separation=rumble_strip",
    "Curbed": "separation=kerb",
    "Rolled Curb": "separation=kerb",
    "Barrier": "separation=jersey_barrier",
    "Bollard": "separation=bollard",
    "Barrier and Bollard": "separation=bollard",
}

_TO_METRIC = Transformer.from_crs(4326, config.METRIC_EPSG, always_xy=True)


def compare():
    """Build data/gaps.geojson + summary from City vs OSM. Returns the summary."""
    data, osm_date, from_cache = _load_osm()
    osm = _osm_ways(data)
    print(f"OSM: {len(osm['road']):,} roads, {len(osm['path']):,} path-like "
          f"ways ({len(osm['bikeway']):,} bikeways), "
          f"{len({w['id'] for w in osm['route']}):,} bicycle route relations")
    city = list(_city_features())
    print(f"City lines: {len(city):,}")

    gaps, summary = match(city, osm)
    _write_gaps(gaps)

    summary.update({"osm_bikeways": len(osm["bikeway"]),
                    "osm_routes": len({w["id"] for w in osm["route"]}),
                    "osm_date": osm_date, "osm_stale": from_cache})
    with open(config.GAPS_COUNT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"On-road lanes: {summary['lane_pos_km']} of {summary['lane_km']} km "
          f"in OSM on their side ({summary['lane_bikeway_km']} km as separate "
          f"cycleways); {summary['lane_absent_km']} km absent, "
          f"{summary['lane_no_km']} km says no; {summary['lane_any_km']} km "
          f"judged any side")
    print(f"Separation: tagged on {summary['sep_ok_km']} of "
          f"{summary['buffer_km']} km of buffered lane OSM has")
    print(f"Off-road: {summary['path_missing_km']} of {summary['path_km']} km "
          f"with no path, {summary['nobike_km']} km on a footway with no "
          f"bicycle access")
    print(f"Signed routes: {summary['unsigned_km']} of {summary['route_km']} km "
          f"with no relation and no tag")
    print(f"Installed {summary['recent_since']}+: {summary['recent_gap_km']} of "
          f"{summary['recent_km']} km not in OSM")
    print("Segments: " + ", ".join(f"{summary[s]:,} {s}" for s in STATUSES))
    if from_cache:
        print(f"NOTE: compared against cached OSM data from {osm_date}, "
              f"not a live Overpass fetch.")
    history.record(summary)
    return summary


# --- OSM source -------------------------------------------------------------

def _overpass_query():
    """The Overpass QL: roads and path-like ways, then bicycle routes."""
    s, w, n, e = config.GUELPH_BBOX
    bbox = f"{s},{w},{n},{e}"
    values = "|".join(config.ROAD_HIGHWAYS + config.PATH_HIGHWAYS)
    # Ways as "tags geom" (tags and coordinates, no node lists). Relations
    # need full "geom" to carry their members' geometry; clipped to the bbox,
    # since the Trans Canada Trail would otherwise bring the whole province.
    return (
        f"[out:json][timeout:{config.OVERPASS_TIMEOUT - 60}];\n"
        f'way["highway"~"^({values})$"]({bbox});\n'
        f"out tags geom({bbox});\n"
        f'relation["route"="bicycle"]({bbox});\n'
        f"out geom({bbox});"
    )


class OsmUnavailable(Exception):
    """Every mirror refused, on a machine that has a working link."""


def _load_osm():
    """Return (data, osm_date, from_cache) for the OSM ways.

    Every mirror is tried, and the whole list is retried: the thing being worked
    around is a loaded instance shedding one request, which clears in seconds.
    Falling back to the cache still beats no gap page, but it is reported rather
    than shrugged off -- ``from_cache`` reaches the published page, and an online
    machine that could not reach any mirror raises so the run can exit non-zero
    and be retried by the scheduler.
    """
    query = _overpass_query()
    print("Querying Overpass for OSM roads, paths and bicycle routes ...")
    for attempt in range(config.OVERPASS_ROUNDS):
        if attempt:
            print(f"  no mirror answered; retrying the list in "
                  f"{config.OVERPASS_ROUND_WAIT}s "
                  f"({attempt + 1} of {config.OVERPASS_ROUNDS})")
            time.sleep(config.OVERPASS_ROUND_WAIT)
        for url in config.OVERPASS_URLS:
            data = _try_overpass(url, query)
            if data is None:
                continue
            with open(config.OSM_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
            osm_base = _osm_base(data)
            _save_fetch(date.today().isoformat(), url, osm_base, data)
            return data, osm_base, False

    # Nothing answered. Ask why before deciding what it means: no link is not a
    # failed build -- the run may as well not have happened -- while a healthy
    # link and no mirror is a real outage worth retrying.
    cached = _load_cache()
    try:
        net.wait_for_link(wait=False)
    except net.LinkUnavailable as e:
        print(f"Warning: no usable link ({e}); Overpass was never reachable.")
        if cached:
            return (*cached, True)
        raise

    if cached:
        print(f"Warning: no Overpass mirror answered in "
              f"{config.OVERPASS_ROUNDS} rounds; falling back to OSM data "
              f"from {cached[1]}.")
        return (*cached, True)
    raise OsmUnavailable(
        f"no Overpass mirror answered in {config.OVERPASS_ROUNDS} rounds "
        f"and there is no cached OSM data"
    )


def _try_overpass(url, query):
    """One attempt at one mirror; None if it failed or answered implausibly."""
    host = urlsplit(url).netloc
    started = time.time()
    try:
        resp = requests.post(
            url,
            data={"data": query},
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.OVERPASS_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"  {host}: {type(e).__name__}: {str(e).splitlines()[0][:120]}")
        return None

    elements = data.get("elements", [])
    count = len(elements)
    if count < config.OSM_MIN_ELEMENTS:
        # HTTP 200 is not proof of an answer. A regional instance replies to an
        # out-of-region bbox with a valid, empty element list, and taking that
        # at face value would report every City facility as missing from OSM.
        print(f"  {host}: {count:,} elements, under the "
              f"{config.OSM_MIN_ELEMENTS:,} floor -- ignoring this reply")
        return None
    routes = sum(1 for el in elements if el.get("type") == "relation")
    if routes < config.OSM_MIN_ROUTES:
        # The relation half of the query timing out leaves the ways intact,
        # and every signed route would then read as unsigned.
        print(f"  {host}: {routes:,} bicycle routes, under the "
              f"{config.OSM_MIN_ROUTES:,} floor -- ignoring this reply")
        return None
    base = _osm_base_time(data)
    if base is None or datetime.now(timezone.utc) - base > timedelta(days=config.OSM_MAX_AGE_DAYS):
        # Nor is a full reply proof of a current one. A lagging mirror answers
        # the query in full from data months old, and the page would present
        # that as this week's OSM. A reply that does not say how old it is
        # gets no benefit of the doubt.
        print(f"  {host}: OSM data from {_osm_base(data)}, not within "
              f"{config.OSM_MAX_AGE_DAYS} days -- ignoring this reply")
        return None
    print(f"  {host}: {count:,} elements ({routes} routes) in "
          f"{time.time() - started:.0f}s, OSM base {_osm_base(data)}")
    return data


def _load_cache():
    """(data, osm_date) for the cached Overpass reply, or None."""
    if not os.path.isfile(config.OSM_CACHE_PATH):
        return None
    with open(config.OSM_CACHE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data, _cache_date()


def _osm_base(data):
    """How current the OSM half of the diff actually is.

    Overpass states this about its own reply, as ``osm3s.timestamp_osm_base``:
    the moment of the last minutely diff the answering mirror had applied. That
    is the honest date for the page, and it is not the same as "today" -- a
    mirror can answer instantly with data from last week. Trimmed to the minute
    for display; the raw value goes in the sidecar.
    """
    stamp = ((data.get("osm3s") or {}).get("timestamp_osm_base") or "").strip()
    if len(stamp) >= 16:
        return f"{stamp[:10]} {stamp[11:16]}Z"
    return "unknown"


def _osm_base_time(data):
    """The same timestamp as an aware datetime, or None if absent or garbled."""
    stamp = ((data.get("osm3s") or {}).get("timestamp_osm_base") or "").strip()
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    # A stamp with no zone cannot be aged against UTC; treat it as garbled.
    return when if when.tzinfo else None


def _cache_date():
    """How current the cached reply is: the sidecar, else the file's mtime."""
    if os.path.isfile(config.OSM_FETCH_PATH):
        with open(config.OSM_FETCH_PATH, encoding="utf-8") as f:
            sidecar = json.load(f)
        for key in ("osm_base", "fetched"):
            if sidecar.get(key):
                return sidecar[key]
    stamp = os.path.getmtime(config.OSM_CACHE_PATH)
    return date.fromtimestamp(stamp).isoformat()


def _save_fetch(fetched, url, osm_base, data):
    with open(config.OSM_FETCH_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "fetched": fetched,
            "mirror": urlsplit(url).netloc,
            "osm_base": osm_base,
            "timestamp_osm_base":
                (data.get("osm3s") or {}).get("timestamp_osm_base"),
        }, f, indent=2)


def _osm_ways(data):
    """Split the reply into roads, path-like ways, bikeways and route lines.

    Each way is {"id", "tags", "g"} with g a metric LineString. "bikeway" is
    the subset of "path" a cyclist is meant to use. "route" has one entry per
    member way of each route=bicycle relation, carrying the relation's id and
    tags. Pedestrian areas (area=yes) are dropped.
    """
    out = {"road": [], "path": [], "bikeway": [], "route": []}
    for el in data.get("elements", []):
        if el.get("type") == "relation":
            for m in el.get("members") or []:
                if m.get("type") != "way":
                    continue
                pts = [(p["lon"], p["lat"]) for p in m.get("geometry") or [] if p]
                if len(pts) >= 2:
                    out["route"].append({"id": el["id"], "tags": el.get("tags") or {},
                                         "g": _line(pts)})
            continue
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        tags = el.get("tags") or {}
        hw = tags.get("highway")
        pts = [(p["lon"], p["lat"]) for p in el["geometry"] if p]
        if len(pts) < 2:
            continue
        way = {"id": el["id"], "tags": tags, "g": _line(pts)}
        if hw in config.ROAD_HIGHWAYS:
            out["road"].append(way)
        elif hw in config.PATH_HIGHWAYS and tags.get("area") != "yes":
            out["path"].append(way)
            if is_bikeway(tags):
                out["bikeway"].append(way)
    return out


def is_bikeway(tags):
    """A way a cyclist is meant to use: highway=cycleway or bicycle=designated."""
    return tags.get("highway") == "cycleway" or tags.get("bicycle") == "designated"


def side_value(tags, side):
    """The cycleway value a road carries on ``side`` ("left" / "right").

    cycleway:<side> wins, then cycleway:both, then a plain cycleway=*. On a
    oneway road a plain cycleway=lane|track is read as the right side only --
    the side traffic keeps to -- so it says nothing about a left-hand lane.
    """
    v = tags.get(f"cycleway:{side}") or tags.get("cycleway:both")
    if v is not None:
        return v
    v = tags.get("cycleway")
    if v is None:
        return None
    if side == "left" and tags.get("oneway") in ("yes", "1") \
            and v in ("lane", "track"):
        return None
    return v


def lane_state(tags, side, contraflow=False):
    """"pos", "no" or "absent": what a road says about a lane on ``side``.

    ``side`` "any" reads all four cycleway keys, for a City line drawn on the
    centreline whose side cannot be told.
    """
    if side == "any":
        vals = [tags.get(k) for k in _CYCLEWAY_KEYS]
    else:
        vals = [side_value(tags, side)]
    if any(v in POSITIVE for v in vals):
        return "pos"
    if contraflow and tags.get("oneway:bicycle") == "no":
        return "pos"
    if any(v in NEGATIVE for v in vals):
        return "no"
    if tags.get("bicycle") == "designated" and all(v is None for v in vals):
        return "pos"
    return "absent"


def has_separation(tags, side, buffer):
    """Does a road record, on ``side``, the buffer the City has?

    Any cycleway[:<side>|:both]:separation* or :buffer* key will do; for a
    physical buffer (not a painted one) so does cycleway:<side>=track, which
    is a lane behind a curb by definition. A value of "separate" says the
    lane is its own way, which carries the separation.
    """
    sides = "(left|right|both)" if side == "any" else f"({side}|both)"
    pat = re.compile(rf"^cycleway(:{sides})?:(separation|buffer)")
    if any(pat.match(k) for k in tags):
        return True
    vals = ([tags.get(k) for k in _CYCLEWAY_KEYS] if side == "any"
            else [side_value(tags, side)])
    if "separate" in vals:
        return True
    return buffer != "Painted" and "track" in vals


def route_tagged(tags):
    """Does a road say it is a bike route, without a relation?

    Any positive cycleway value will do, and so does bicycle=designated, which
    is how Guelph's signed shared streets are mostly tagged -- often beside a
    cycleway:both=no, since a signed route has no lane.
    """
    return lane_state(tags, "any") == "pos" or tags.get("bicycle") == "designated"


def bike_access(tags):
    """"ok" or "nobike": may a cyclist use this path-like way?"""
    bicycle = tags.get("bicycle")
    if bicycle in ("no", "dismount"):
        return "nobike"
    if tags.get("highway") in _FOOT_ONLY and bicycle not in _BIKE_OK:
        return "nobike"
    return "ok"


# --- City source ------------------------------------------------------------

def _city_features():
    with open(config.SLIM_PATH, encoding="utf-8") as f:
        for line in f:
            feat = json.loads(line)
            geom = feat["geometry"]
            parts = (geom["coordinates"] if geom["type"] == "MultiLineString"
                     else [geom["coordinates"]])
            lines = [_line(p) for p in parts if len(p) >= 2]
            if lines:
                yield {"props": feat.get("properties") or {},
                       "geom": geom, "lines": lines}


def _line(pts):
    """A metric shapely LineString from (lon, lat) pairs."""
    xs, ys = _TO_METRIC.transform([p[0] for p in pts], [p[1] for p in pts])
    return shapely.linestrings(np.column_stack([xs, ys]))


def group_of(props):
    """"lane", "path", "route" or "spot": which rule matches this City row."""
    ftype = props.get("type")
    if props.get("kind") == "spot":
        return "spot"
    if ftype == "Signed Route":
        return "route"
    if ftype in config.LANE_TYPES and props.get("onroad"):
        return "lane"
    return "path"


# --- Matching ---------------------------------------------------------------

def match(city, osm, today=None):
    """Classify every City line. Returns (gap features, summary dict).

    ``city`` items are {"props", "geom", "lines": [metric LineString]};
    ``osm`` is {"road"|"path"|"bikeway"|"route": [{"id", "tags", "g"}]}.
    """
    today = today or date.today()
    new_since = today.year - config.NEW_YEARS
    groups = [group_of(c["props"]) for c in city]
    pts, bear, weights, owner = _sample(city)
    grp = np.array([groups[i] for i in owner], dtype=object)

    roads = _aligned(pts, bear, osm["road"], config.ROAD_M)
    bikeways = _aligned(pts, bear, osm["bikeway"], config.BIKEWAY_M)
    paths = _aligned(pts, bear, osm["path"], config.PATH_M, fallback=True)
    routes = _aligned(pts, bear, osm["route"], config.ROUTE_M)
    named = [w for w in osm["road"] if w["tags"].get("name")]
    streets = _aligned(pts, bear, named, config.STREET_M, fallback=True)

    per = [Counter() for _ in city]          # sample class -> metres
    sep = [Counter() for _ in city]          # "ok"/"lack" -> metres
    sides = [Counter() for _ in city]        # side -> metres
    blame = [defaultdict(Counter) for _ in city]  # class -> way id -> metres
    names = [Counter() for _ in city]
    for k in range(len(pts)):
        i, w, g = owner[k], weights[k], grp[k]
        p = city[i]["props"]
        if streets["idx"][k] >= 0:
            names[i][named[streets["idx"][k]]["tags"]["name"]] += w
        if g == "spot":
            continue
        cls, way, side = _classify(k, g, p, osm, roads, bikeways, paths, routes)
        per[i][cls] += w
        if way is not None:
            blame[i][cls][way] += w
        if side is not None:
            sides[i][side] += w
        if g == "lane" and cls in ("pos", "bikeway") and p.get("buffer"):
            ok = cls == "bikeway" or has_separation(
                osm["road"][roads["idx"][k]]["tags"], side, p["buffer"])
            sep[i]["ok" if ok else "lack"] += w
            if not ok:
                blame[i]["lack"][way] += w

    gaps = []
    counts = Counter()
    for i, c in enumerate(city):
        p = c["props"]
        status, gap = segment_status(groups[i], p, per[i], sep[i], new_since)
        if status is None:
            continue
        counts[status] += 1
        length = sum(per[i].values()) or float(p.get("length") or 0)
        covered = sum(per[i][k] for k in COVERED[groups[i]])
        side = sides[i].most_common(1)[0][0] if sides[i] else None
        way = _blame_way(gap or status, blame[i])
        street = (names[i].most_common(1)[0][0] if names[i]
                  else p.get("street", ""))
        gaps.append(_gap_feature(c, status, gap, length, length - covered,
                                 street, side, way,
                                 tag_hint(gap or status, p, side)))

    summary = _summary(city, groups, per, sep, counts, new_since, roads,
                       pts, weights, owner)
    return gaps, summary


# Sample classes that count as covered, per rule.
COVERED = {
    "lane": ("pos", "bikeway"),
    "path": ("ok", "nobike"),
    "route": ("relation", "bikeway", "road_pos"),
    "spot": (),
}


def _classify(k, group, props, osm, roads, bikeways, paths, routes):
    """(class, OSM way id, side) for sample k of a City line in ``group``."""
    if group == "lane":
        if bikeways["idx"][k] >= 0:
            return "bikeway", osm["bikeway"][bikeways["idx"][k]]["id"], None
        r = roads["idx"][k]
        if r < 0:
            return "noroad", None, None
        side = ("any" if roads["dist"][k] < config.SIDE_MIN_M
                else roads["side"][k])
        state = lane_state(osm["road"][r]["tags"], side,
                           contraflow=props.get("type") == "Contraflow")
        return state, osm["road"][r]["id"], side
    if group == "path":
        q = paths["idx"][k]
        if q >= 0:
            way = osm["path"][q]
            return bike_access(way["tags"]), way["id"], None
        r = roads["idx"][k]
        if props.get("type") == "Cycle Track" and r >= 0 \
                and roads["dist"][k] >= config.SIDE_MIN_M \
                and lane_state(osm["road"][r]["tags"], roads["side"][k]) == "pos":
            return "ok", osm["road"][r]["id"], None
        return "missing", None, None
    # group == "route"
    if routes["idx"][k] >= 0:
        return "relation", osm["route"][routes["idx"][k]]["id"], None
    if bikeways["idx"][k] >= 0:
        return "bikeway", osm["bikeway"][bikeways["idx"][k]]["id"], None
    r = roads["idx"][k]
    if r >= 0 and route_tagged(osm["road"][r]["tags"]):
        return "road_pos", osm["road"][r]["id"], None
    return "none", (osm["road"][r]["id"] if r >= 0 else None), None


def segment_status(group, props, lengths, sep, new_since):
    """(status, underlying gap kind or None) for one City segment.

    ``lengths`` maps sample classes to metres, ``sep`` maps "ok"/"lack" to
    the metres of covered, buffered lane that do / do not record the buffer.
    A status of None means the segment is not listed.
    """
    if group == "spot":
        return ("spot", None) if props.get("status") == "in_service" else (None, None)
    total = sum(lengths.values())
    if total <= 0:
        return None, None
    covered = sum(lengths.get(k, 0) for k in COVERED[group])
    matched = covered / total >= config.MATCHED_SHARE
    if props.get("status") != "in_service":
        if props.get("status") == "planned" and not matched:
            return "planned", None
        return None, None
    if matched:
        if total < config.MIN_LISTED_M:
            return None, None
        if group == "lane" and sum(sep.values()) \
                and sep.get("lack", 0) >= config.NOSEP_SHARE * sum(sep.values()):
            return "nosep", None
        if group == "path" and lengths.get("nobike", 0) >= 0.5 * covered:
            return "nobike", None
        return None, None
    if total - covered < config.MIN_LISTED_M:
        return None, None
    if group == "route":
        gap = "unsigned_route"
    elif group == "lane" and lengths.get("no", 0) >= total - covered - lengths.get("no", 0):
        gap = "says_no"
    else:
        gap = "missing"
    if gap in NEW_FROM and (props.get("year") or 0) >= new_since:
        return "new", gap
    return gap, None


def tag_hint(kind, props, side):
    """The tag a mapper adds for a segment of status ``kind`` (a gap kind)."""
    ftype = props.get("type")
    buffer = props.get("buffer")
    s = side if side in ("left", "right") else "<left|right>"
    if kind == "nosep":
        return f"cycleway:{s}:{SEPARATION_TAG.get(buffer, 'separation=*')}"
    if kind == "nobike":
        if ftype == "MUP":
            return "bicycle=designated + segregated=no"
        return "highway=cycleway"
    if kind == "unsigned_route":
        return "route=bicycle relation (network=lcn) over this street"
    if kind in ("missing", "says_no"):
        if group_of(props) == "path":
            if ftype == "MUP":
                return ("highway=path + bicycle=designated + foot=designated"
                        " + segregated=no")
            return "highway=cycleway"
        value = "track" if ftype == "Cycle Track" else "lane"
        tags = [f"cycleway:{s}={value}"]
        if ftype == "Contraflow":
            tags += [f"cycleway:{s}:oneway=-1", "oneway:bicycle=no"]
        if ftype == "Bike Lane - Green":
            tags.append(f"cycleway:{s}:surface:colour=green")
        if buffer in SEPARATION_TAG:
            tags.append(f"cycleway:{s}:{SEPARATION_TAG[buffer]}")
        hint = " + ".join(tags)
        if side == "any":
            hint += " (City line is on the centreline: check the side)"
        return hint
    return ""


def _blame_way(kind, blame):
    """The OSM way a listed segment is about: the road to tag, the footway to
    retag, the road saying no."""
    cls = {"missing": ("absent", "no"), "says_no": ("no",), "nosep": ("lack",),
           "nobike": ("nobike",), "unsigned_route": ("none",)}.get(kind, ())
    best = Counter()
    for c in cls:
        best.update(blame.get(c, {}))
    return best.most_common(1)[0][0] if best else None


def _summary(city, groups, per, sep, counts, new_since, roads, pts, weights,
             owner):
    in_service = [c["props"].get("status") == "in_service" for c in city]

    def km(group, classes=None):
        m = 0.0
        for i, g in enumerate(groups):
            if g == group and in_service[i]:
                m += (sum(per[i].values()) if classes is None
                      else sum(per[i][k] for k in classes))
        return _km(m)

    any_m = sum(weights[k] for k in range(len(pts))
                if groups[owner[k]] == "lane" and in_service[owner[k]]
                and roads["idx"][k] >= 0 and roads["dist"][k] < config.SIDE_MIN_M)
    recent = [i for i, c in enumerate(city) if in_service[i]
              and groups[i] != "spot" and (c["props"].get("year") or 0) >= new_since]
    recent_m = sum(sum(per[i].values()) for i in recent)
    recent_gap_m = sum(sum(per[i].values()) - sum(per[i][k] for k in COVERED[groups[i]])
                       for i in recent)
    return {
        "city": sum(1 for i, g in enumerate(groups) if in_service[i] and g != "spot"),
        "city_km": _km(sum(sum(p.values()) for i, p in enumerate(per) if in_service[i])),
        "lane_km": km("lane"),
        "lane_pos_km": km("lane", ("pos", "bikeway")),
        "lane_bikeway_km": km("lane", ("bikeway",)),
        "lane_absent_km": km("lane", ("absent", "noroad")),
        "lane_no_km": km("lane", ("no",)),
        "lane_any_km": _km(any_m),
        "buffer_km": _km(sum(sum(s.values()) for i, s in enumerate(sep) if in_service[i])),
        "sep_ok_km": _km(sum(s["ok"] for i, s in enumerate(sep) if in_service[i])),
        "path_km": km("path"),
        "path_missing_km": km("path", ("missing",)),
        "nobike_km": km("path", ("nobike",)),
        "route_km": km("route"),
        "unsigned_km": km("route", ("none",)),
        "recent_since": new_since,
        "recent_km": _km(recent_m),
        "recent_gap_km": _km(recent_gap_m),
        "work": sum(counts[s] for s in WORK_STATUSES),
        **{s: counts[s] for s in STATUSES},
    }


def _sample(city):
    """Points every ~SAMPLE_STEP_M along each City line.

    Returns (points, local bearing in radians mod pi, length each stands for,
    owning feature index). Each part is cut into equal pieces and sampled at
    their midpoints, so the weights of a line sum to its length.
    """
    pts, bear, weights, owner = [], [], [], []
    for i, c in enumerate(city):
        for ln in c["lines"]:
            length = ln.length
            if length <= 0:
                continue
            n = max(1, int(round(length / config.SAMPLE_STEP_M)))
            d = (np.arange(n) + 0.5) * (length / n)
            pts.extend(shapely.line_interpolate_point(ln, d))
            same = np.empty(n, dtype=object)
            same[:] = [ln] * n
            bear.extend(_bearing(same, d))
            weights.extend([length / n] * n)
            owner.extend([i] * n)
    return (np.array(pts, dtype=object), np.array(bear), np.array(weights),
            np.array(owner, dtype=int))


def _bearing(lines, d, half=2.0):
    """Direction (radians, mod pi) of each line around distance d along it."""
    lengths = shapely.length(lines)
    a = shapely.line_interpolate_point(lines, np.clip(d - half, 0, lengths))
    b = shapely.line_interpolate_point(lines, np.clip(d + half, 0, lengths))
    return np.mod(np.arctan2(shapely.get_y(b) - shapely.get_y(a),
                             shapely.get_x(b) - shapely.get_x(a)), math.pi)


def _aligned(pts, bear, ways, maxd, fallback=False):
    """Each point's nearest way within maxd whose direction agrees with its own.

    Returns {"idx", "dist", "side"}: an index into ``ways`` (-1 for none), the
    distance, and "left"/"right" -- which side of that way's direction the
    point lies on. With ``fallback`` a point with no agreeing way takes the
    plain nearest instead.
    """
    n = len(pts)
    out = {"idx": np.full(n, -1), "dist": np.full(n, np.inf),
           "side": np.full(n, None, dtype=object)}
    if not ways or not n:
        return out
    geoms = np.array([w["g"] for w in ways], dtype=object)
    tree = shapely.STRtree(geoms)
    pi, ti = tree.query(pts, predicate="dwithin", distance=maxd)
    if not len(pi):
        return out
    g = geoms[ti]
    p = pts[pi]
    dist = shapely.distance(p, g)
    s = shapely.line_locate_point(g, p)
    lengths = shapely.length(g)
    a = shapely.line_interpolate_point(g, np.clip(s - 2.0, 0, lengths))
    b = shapely.line_interpolate_point(g, np.clip(s + 2.0, 0, lengths))
    q = shapely.line_interpolate_point(g, s)
    ax, ay, bx, by = shapely.get_x(a), shapely.get_y(a), shapely.get_x(b), shapely.get_y(b)
    road_bear = np.mod(np.arctan2(by - ay, bx - ax), math.pi)
    diff = np.abs(road_bear - bear[pi])
    diff = np.minimum(diff, math.pi - diff)
    agrees = diff <= math.radians(config.BEARING_MAX_DEG)
    cross = (bx - ax) * (shapely.get_y(p) - shapely.get_y(q)) - \
        (by - ay) * (shapely.get_x(p) - shapely.get_x(q))

    # Nearest agreeing candidate per point; then, with fallback, the nearest
    # of any for the points that had none.
    order = np.lexsort((dist, ~agrees, pi))
    first = np.ones(len(order), dtype=bool)
    first[1:] = pi[order][1:] != pi[order][:-1]
    pick = order[first]
    keep = agrees[pick] | fallback
    pick = pick[keep]
    out["idx"][pi[pick]] = ti[pick]
    out["dist"][pi[pick]] = dist[pick]
    out["side"][pi[pick]] = np.where(cross[pick] > 0, "left", "right")
    return out


def _gap_feature(c, status, gap, length, untraced, street, side, way, tag):
    p = c["props"]
    props = {"status": status, "street": street,
             "length": int(round(length)), "untraced": int(round(untraced))}
    if gap:
        props["gap"] = gap
    for k in ("id", "type", "kind", "buffer", "year"):
        if p.get(k) is not None:
            props[k] = p[k]
    if side:
        props["side"] = side
    if way is not None:
        props["way"] = way
    if tag:
        props["tag"] = tag
    return {"type": "Feature", "properties": props,
            "geometry": {"type": c["geom"]["type"],
                         "coordinates": _round(c["geom"]["coordinates"])}}


def _write_gaps(gaps):
    with open(config.GAPS_GEOJSON_PATH, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": gaps}, f,
                  separators=(",", ":"))


def _km(m):
    return round(float(m) / 1000, 1)


def _round(c):
    if isinstance(c, (int, float)):
        return round(c, 6)  # ~0.1 m
    return [_round(x) for x in c]
