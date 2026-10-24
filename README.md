# Guelph Bike Layer

Turns the City of Guelph [Bike Facilities](https://gismaps.guelph.ca/hosting/rest/services/OpenData/OpenData2/FeatureServer/1)
layer (1,514 lines, 210 km in service) into map-tile layers that OpenStreetMap
mappers can add to the **JOSM** and **iD** editors as a reference overlay, and
a weekly work list of what OSM is missing: newest City installs first, each
row with the tag to add and a link that opens the spot in iD or JOSM.

**Live layer and how to add it: https://guelph-maps.github.io/guelph-bike-layer/**
&middot; work list: https://guelph-maps.github.io/guelph-bike-layer/gaps/

Part of the [guelph-maps](https://github.com/guelph-maps) organisation, which
indexes every Guelph project. Cloned from
[guelph-sidewalks-layer](https://github.com/guelph-maps/guelph-sidewalks-layer),
the family's first line layer; this is its second.

## Why this layer

The audit put Bike Facilities at tier 4 because "OSM lacks separation" and
233 OSM ways said `cycleway=no` on City bike streets. A side-aware match
(`findings/recalibration.md` in
[guelph-osm-import-audit](https://github.com/guelph-maps/guelph-osm-import-audit))
found OSM already about 98% complete on lane presence and 80% on separation,
leaving a backlog an afternoon could clear. What makes it worth a weekly page
is churn: it is the fastest-changing layer the City publishes (52 rows added
between the audit and 2026-10-09, 61 rows dated 2026 against the audit's 7).
So the page's job is to catch new installs, and it leads with them.

On the first run here (City data and OSM both 2026-10-24):

- **On-road lanes:** OSM has the lane on the City's side of the road for
  **121.6 of 124.0 km** (1.9 km of it as separate cycleways). 1.5 km has no
  tag on that side and 0.8 km says `no` (the recalibration: 2.7 km together).
  2.9 km of City lane line is drawn within 1.5 m of the road centreline, where
  its side cannot be read; it is judged on any side, and its rows say so.
- **Separation:** where the City records a buffer, OSM tags it on **18.0 of
  22.7 km** (recalibration: 17.5 of 21.9). The rest is Downey Rd 2.1 km,
  Victoria Rd N 1.2 and Gordon St 0.5, as the recalibration found.
- **Signed routes:** 3.1 of 54.5 km have no `route=bicycle` relation, no
  cycleway tag and no `bicycle=designated` on the road: Emma St 1.4 km, Hearn
  Ave 0.8, Fountain St E 0.4, Earl St 0.35 (recalibration: 3.1 km).
- **Off-road paths:** 0.1 of 28.4 km have no path at all; 0.5 km is on a
  sidewalk with no bicycle access. The recalibration said 1.3 km, but it took
  the nearest path, which for a cycle track is usually the sidewalk beside it;
  here a cycle track looks for a cycleway within 15 m first.
- **New installs:** of the 10.5 km the City dated 2025 or 2026, **2.4 km is
  not in OSM** (the recalibration's 1.45 of 5.55 km counted on-road lanes
  only). That is 15 segments, as 11 jobs: Hearn Ave and Inkerman St signed
  routes (2026), Downey Rd's 2026 lanes, Woolwich St lanes OSM says `no` to.
- **70 segments of work** in all (15 new, 3 missing, 6 says no, 22 no
  separation, 8 no bikes, 16 unsigned route), which the page folds into 44
  jobs; plus 92 crossrides and intersection pieces, shown and not counted.

## What it produces

- **Vector tiles** (MVT), z14&ndash;19 &mdash; interactive in iD; click a line
  to read its `id` (the City's BIKEFACILITYID), `status`, `type`, `kind`,
  `onroad`, `buffer`, `year`, `width`, `signed`, `street` and `length`.
- **Raster tiles** (PNG), z14&ndash;17 &mdash; coloured by what is on the
  ground: painted lane blue, buffered violet, separated (cycle track, curb,
  bollards) green, multi-use path orange, signed route amber dashed,
  crossrides pink, planned grey dashed. Out-of-service rows are not drawn.
- A **landing page** with the colour key, copy-paste "add this layer"
  instructions for both editors, and the tags each kind maps to.
- A **work list** ([`/gaps/`](https://guelph-maps.github.io/guelph-bike-layer/gaps/)),
  one row per job (the City's per-block pieces of one street that need the
  same tag), newest install first. Each row gives the tag to add, relative to
  the OSM way's direction, and links to iD (with the way selected), JOSM
  (remote control: the area loaded, the way selected) and openstreetmap.org;
  <kbd>I</kbd>, <kbd>J</kbd> and <kbd>O</kbd> do the same for the selected row.
  Statuses:
  - **new** &mdash; installed this year or last, and not in OSM (any of the
    next three); listed first;
  - **missing** &mdash; no lane tag on its side, no separate cycleway, no path;
  - **says_no** &mdash; the OSM road says `cycleway=no` on the side the City
    has a lane;
  - **nosep** &mdash; the lane is in OSM but the City's curb, bollards, rumble
    strip or painted buffer is not;
  - **nobike** &mdash; a multi-use path or cycle track mapped as a sidewalk
    with no bicycle access;
  - **unsigned_route** &mdash; a signed route with no relation and no tag;
  - off by default: **planned** (City status Planned) and **spot**
    (crossrides, intersection treatments, curb cuts: no settled OSM tag, so
    shown and never counted).

  Its [history page](https://guelph-maps.github.io/guelph-bike-layer/gaps/history.html)
  charts the counts and kilometres, one point per weekly run.

All of it is published to GitHub Pages and rebuilt weekly.

## How the work list matches

Overpass returns every road and path-like way in the Guelph bbox, and every
`route=bicycle` relation with its members' geometry clipped to it (one query,
~18,000 elements). Each City line is cut into ~5 m pieces, and each piece's
midpoint asks:

- **On-road lanes** (Bike Lane, Green, Contraflow, an on-road Cycle Track):
  a separate cycleway within 12 m covers it; else the nearest road within
  20 m is read on the piece's side &mdash; `cycleway:<side>`, then
  `cycleway:both`, then a plain `cycleway=*` (on a oneway road, the right side
  only). Contraflow also accepts `oneway:bicycle=no`.
- **Off-road** (MUP, an off-road Cycle Track): a path-like way within 15 m;
  `nobike` when it is a footway with no `bicycle=yes|designated|permissive`.
  A cycle track checks for a cycleway, or a `cycleway:<side>=track` on the
  road, before the sidewalk beside it.
- **Signed routes:** a relation member within 15 m, a separate cycleway, or a
  road with a positive cycleway value or `bicycle=designated` (how Guelph
  mostly tags its signed shared streets).

A road or cycleway only answers when its direction agrees with the City
line's within 30°: at an intersection the nearest road is often the cross
street. A segment is in OSM at &ge;70% covered (by length); otherwise it is a
gap, named by what most of its uncovered length says. Gaps under 15 m (the
corner pieces of protected intersections) are not listed. The full rule is in
[`src/compare.py`](src/compare.py)'s docstring; matching runs in UTM 17N
metres with shapely's STRtree and takes about a second; the Overpass
fetch takes ~40 s.

Rows are named after the nearest named OSM road, so the City's spelling slips
("Wyndham Street Souuth") do not reach the page; they were reported to the
City on 2026-10-12.

It runs one way only. An OSM cycleway the City does not inventory (campus,
private sites) is not reported.

The Overpass handling (mirror list, retries, refusing stale or implausibly
small replies, the cache fallback, exit code 70) is the parks layer's, by way
of sidewalks; its README explains each piece. A reply must carry a
`timestamp_osm_base` with a time zone, within 3 days, at least 9,000 elements
(`OSM_MIN_ELEMENTS`, half the first reply) and at least 8 bicycle route
relations (`OSM_MIN_ROUTES`, half of 17): a reply whose relation half came
back empty would otherwise call every signed route unsigned.

The download pages through the City's 1,000-row cap and refuses to save if
the total differs from the service's own count.

## Setup

1. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```
   `addressvault` is the local link-gate package the sibling projects share; it
   is not on PyPI. Like the sidewalks layer, this needs **shapely 2, numpy and
   pyproj** for the spatial index and the metric projection.
2. On Windows, set up WSL2 + tippecanoe once &mdash; see
   [wsl-setup.md](wsl-setup.md). Elsewhere, install tippecanoe (2.49+) and the
   vector step runs it directly.

## Usage

```
python run.py download   # fetch the Bike Facilities layer, page by page (smart-cached)
python run.py slim       # reduce to a slim GeoJSONL
python run.py compare    # diff City facilities against OSM -> data/gaps.geojson
python run.py vector     # build vector (MVT) tiles via tippecanoe
python run.py raster     # build line raster (PNG) tiles
python run.py site       # render the landing page (+ the work list and history)
python run.py publish    # force-push the site to the gh-pages branch

python run.py build      # download + slim + compare + vector + raster + site
python run.py update     # build + publish  (the scheduled entry point)
```

Build output lands in `build/site/`; that directory is what gets published.
The first full build (2026-10-24): 5,963 vector tiles and 1,104 raster tiles,
about two minutes in all.

## Scheduling (Windows)

```powershell
.\schedule-add.ps1       # registers a weekly task "kk-GuelphBikeLayer", Thursdays 19:30
.\schedule-remove.ps1    # unregisters it
```

Thursday, not Wednesday: Wednesday 19:30 went to toronto-poster-columns-layer
the same day, and the slots exist so no two builds drive tippecanoe at once.

## Tests

```
pytest
```

## Licence / attribution

Bike facility data is &copy; City of Guelph, published under the
[Open Government Licence &ndash; City of Guelph](https://gismaps.guelph.ca/Images/OpenDataLicenceVersion2.pdf).
The OSMF Licence Working Group approved that licence as `compatible` on
2024-09-09.

**This project redistributes City data** — as published tiles on a public URL
— and the licence attaches a required attribution to that. The landing page,
the work list and the history page all carry, visibly:

> Contains information licensed under the Open Government Licence – City of Guelph.

linked to the licence text. The same attribution is embedded in the vector tile
metadata. This is a condition of use, not a courtesy: if you fork this, the
notice travels with it.

Being able to map from this layer is not the same as being cleared to
bulk-import it. Adding a lane or a buffer at a time, by a mapper checking
imagery or the street, is ordinary mapping with an approved source. A scripted
upload of the City's tags would be an import, and would need its own proposal
under the [import guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines).
