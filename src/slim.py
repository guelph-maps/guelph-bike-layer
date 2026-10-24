"""Reduce the Bike Facilities GeoJSON to a slim newline-delimited GeoJSON.

Every line is kept, whatever its status, and its properties are cut down to
the ones a mapper can use:

  id         the City's BIKEFACILITYID (it rises with each row the City adds)
  status     "in_service", "planned" or "out_of_service"
  type       FACILITYTYPE as the City writes it ("Bike Lane", "MUP", ...)
  kind       what it is on the ground, derived (see config.py): painted,
             buffered, separated, mup, route or spot
  onroad     true / false
  buffer     BUFFERTYPE, when there is one ("Painted", "Curbed", ...)
  year       INSTALLYEAR
  width      FACILITYWIDTH in metres, when given
  signed     true / false, when given
  street     the City's STREETNAME
  length     metres, rounded

The one file, data/bike-slim.geojsonl, feeds the tile builders and the gap
tool alike; data/bike.count.json holds the counts the pages quote.
"""

import json
import os
from collections import Counter

import ijson

from src import config

# Sanity bounds for the slimmed feature count (1,514 lines on 2026-10-24).
MIN_EXPECTED = 1_200
MAX_EXPECTED = 2_500

_STATUS = {config.IN_SERVICE: "in_service", config.PLANNED: "planned"}


def slim(src_path):
    """Stream the GeoJSON into data/bike-slim.geojsonl.

    Returns the slim file path. Raises if the feature count is implausible.
    """
    print(f"Slimming {src_path} ...")
    os.makedirs(config.DATA_DIR, exist_ok=True)

    count = skipped = 0
    kinds = Counter()
    kind_m = Counter()
    years = Counter()
    with open(src_path, "rb") as src, \
            open(config.SLIM_PATH, "w", encoding="utf-8") as out:
        for feature in ijson.items(src, "features.item"):
            geom = feature.get("geometry") or {}
            if geom.get("type") not in ("LineString", "MultiLineString") \
                    or not geom.get("coordinates"):
                skipped += 1
                continue
            props = slim_props(feature.get("properties") or {})
            out.write(json.dumps({
                "type": "Feature",
                "geometry": {
                    "type": geom["type"],
                    "coordinates": _plain(geom["coordinates"]),
                },
                "properties": props,
            }) + "\n")
            count += 1
            if props["status"] == "in_service":
                kinds[props["kind"]] += 1
                kind_m[props["kind"]] += props.get("length", 0)
                if props.get("year"):
                    years[props["year"]] += 1

    latest = max(years) if years else None
    in_service = sum(kinds.values())
    with open(config.COUNT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "lines": count, "in_service": in_service,
            "in_service_km": round(sum(kind_m.values()) / 1000, 1),
            "kinds": dict(kinds),
            "kind_km": {k: round(m / 1000, 1) for k, m in kind_m.items()},
            "latest_year": latest,
            "latest_year_rows": years.get(latest, 0),
        }, f)

    print(f"Done: {config.SLIM_PATH} ({count:,} lines, {in_service:,} in "
          f"service, {skipped:,} skipped)")
    print("  in service: " + ", ".join(
        f"{kinds[k]:,} {k} ({kind_m[k] / 1000:.1f} km)" for k in sorted(kinds)))
    if not MIN_EXPECTED <= count <= MAX_EXPECTED:
        raise RuntimeError(
            f"Slim feature count {count:,} is outside the expected range "
            f"{MIN_EXPECTED:,}-{MAX_EXPECTED:,} -- aborting."
        )
    return config.SLIM_PATH


def slim_props(props_in):
    """The kept properties of one City facility."""
    props = {}
    fid = props_in.get(config.ID_KEY)
    if fid is not None:
        props["id"] = int(fid)
    status = str(props_in.get(config.STATUS_KEY) or "").strip()
    props["status"] = _STATUS.get(status, "out_of_service")
    ftype = str(props_in.get(config.TYPE_KEY) or "Other").strip()
    props["type"] = ftype
    onroad = str(props_in.get(config.ONROAD_KEY) or "").strip() == "Yes"
    buffer = str(props_in.get(config.BUFFER_KEY) or "").strip()
    if buffer in ("None", "Other"):
        buffer = ""
    props["kind"] = facility_kind(ftype, buffer)
    props["onroad"] = onroad
    if buffer:
        props["buffer"] = buffer
    year = props_in.get(config.YEAR_KEY)
    if year:
        props["year"] = int(year)
    width = props_in.get(config.WIDTH_KEY)
    if width:
        props["width"] = round(float(width), 2)
    signed = props_in.get(config.SIGNED_KEY)
    if signed in ("Yes", "No"):
        props["signed"] = signed == "Yes"
    street = str(props_in.get(config.STREET_KEY) or "").strip()
    if street:
        props["street"] = street
    length = props_in.get("Shape__Length")
    if length is not None:
        props["length"] = int(round(float(length)))
    return props


def facility_kind(ftype, buffer):
    """painted / buffered / separated / mup / route / spot, for one row."""
    if ftype in config.SPOT_TYPES:
        return "spot"
    if ftype == "MUP":
        return "mup"
    if ftype == "Signed Route":
        return "route"
    if ftype == "Cycle Track" or buffer in config.SEPARATED_BUFFERS:
        return "separated"
    if buffer in config.PAINTED_BUFFERS:
        return "buffered"
    return "painted"


def _plain(coords):
    """Recursively convert ijson Decimals to floats for compact json output."""
    if isinstance(coords, list):
        return [_plain(c) for c in coords]
    return float(coords)
