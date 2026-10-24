// Gap-review page: City raster layer + gap segments, driven by a work list.
//
// The sidewalks layer's page, flattened. Its gaps were thousands of short
// segments, so it led with streets; here the list is tens of rows and the
// question is "what did the City build lately that OSM does not have", so the
// table is one row per job, newest install first, each carrying the tag to
// add and links that open the spot in iD or JOSM. A job is the City segments
// of one street that need the same tag: the City cuts a street into pieces
// at every block, and four rows saying "Hearn Avenue, add it to a route"
// would be one piece of work.

(function () {
  "use strict";

  // Order is the checkbox / count-chip order. Default-on statuses first.
  var STATUSES = ["new", "missing", "says_no", "nosep", "nobike",
                  "unsigned_route", "planned", "spot"];
  var COLORS = {
    new: "#c2255c", missing: "#f08c00", says_no: "#e03131", nosep: "#1098ad",
    nobike: "#7048e8", unsigned_route: "#66a80f", planned: "#868e96",
    spot: "#adb5bd",
  };
  var LABELS = {
    new: "new", missing: "missing", says_no: "OSM says no",
    nosep: "no separation", nobike: "no bikes",
    unsigned_route: "unsigned route", planned: "planned", spot: "not counted",
  };
  // Jobs sort by status rank first only to keep "new" on top; within the
  // work statuses it is the install year that orders the list.
  var RANK = { new: 0, missing: 1, says_no: 1, nosep: 1, nobike: 1,
               unsigned_route: 1, planned: 2, spot: 3 };
  var WEIGHT = 5, SELECTED_WEIGHT = 9;
  // Metres of padding around a job for the JOSM download box.
  var PAD_M = 40;
  var JOSM = "http://127.0.0.1:8111/load_and_zoom";

  var map;
  var features = [];
  var lines = [];          // L.Polyline per feature, indexed like features
  var jobs = [];           // {idx: [feature index...], p, length, untraced, way, mid, bounds}
  var jobOf = [];          // feature index -> job index
  var selectedRow = null;
  var selectedJob = null;  // job index of the current selection

  function init() {
    var el = document.getElementById("gap-map");
    if (!el || typeof L === "undefined" || !el.dataset.geojson) {
      return;
    }
    map = L.map(el, { preferCanvas: true, renderer: L.canvas({ tolerance: 6 }) })
      .setView([43.5448, -80.2482], 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">' +
        "OpenStreetMap</a> contributors",
    }).addTo(map);
    if (el.dataset.raster) {
      L.tileLayer(el.dataset.raster, {
        minZoom: parseInt(el.dataset.rasterMinzoom, 10),
        maxNativeZoom: parseInt(el.dataset.rasterMaxzoom, 10),
        maxZoom: 19,
        opacity: 0.6,
      }).addTo(map);
    }

    fetch(el.dataset.geojson)
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function (e) {
        el.innerHTML = '<p style="padding:1rem">Could not load gaps.geojson.</p>';
        console.error(e);
      });
  }

  function render(data) {
    features = data.features || [];
    features.forEach(function (f, i) {
      var g = f.geometry;
      f._mid = midpoint(g);
      f._bounds = bounds(g);
      var latlngs = L.GeoJSON.coordsToLatLngs(g.coordinates,
        g.type === "MultiLineString" ? 1 : 0);
      var line = L.polyline(latlngs, {
        color: COLORS[f.properties.status] || "#888",
        weight: WEIGHT,
        opacity: 0.9,
      });
      line.bindPopup(function () { return popupHtml(f, i); });
      line.on("click", function (ev) {
        L.DomEvent.stopPropagation(ev);
        select(jobOf[i], false, ev.latlng, i);
      });
      lines[i] = line;
    });
    groupJobs();
    buildTable();
    wireControls();
  }

  // One job per status, street, facility, buffer, year and tag (the tag
  // carries the side, so a street's two lanes stay two jobs). Spot rows are
  // not work, and stay one row each.
  function groupJobs() {
    var byKey = {};
    features.forEach(function (f, i) {
      var p = f.properties;
      var key = p.status === "spot" ? "spot#" + i :
        [p.status, p.gap, p.street, p.type, p.buffer, p.year, p.tag].join("|");
      if (byKey[key] === undefined) {
        byKey[key] = jobs.length;
        jobs.push({ idx: [], p: p, length: 0, untraced: 0, ways: {},
                    bounds: null, mid: null, longest: -1, maxId: 0 });
      }
      var job = jobs[byKey[key]];
      job.idx.push(i);
      job.length += p.length || 0;
      job.untraced += p.untraced || 0;
      job.maxId = Math.max(job.maxId, p.id || 0);
      if (p.way != null) {
        job.ways[p.way] = (job.ways[p.way] || 0) + (p.length || 0);
      }
      if ((p.length || 0) > job.longest) {
        job.longest = p.length || 0;
        job.mid = f._mid;
      }
      var b = f._bounds;
      job.bounds = job.bounds
        ? [Math.min(job.bounds[0], b[0]), Math.min(job.bounds[1], b[1]),
           Math.max(job.bounds[2], b[2]), Math.max(job.bounds[3], b[3])]
        : b;
    });
    jobs.forEach(function (job) {
      // The OSM way most of the job is about: the one iD and JOSM select.
      var best = null, bestM = -1;
      Object.keys(job.ways).forEach(function (w) {
        if (job.ways[w] > bestM) { bestM = job.ways[w]; best = w; }
      });
      job.way = best;
    });
    // Newest install first; then the higher City id (it rises with every row
    // the City adds); then the longer job.
    jobs.sort(function (a, b) {
      return (RANK[a.p.status] - RANK[b.p.status]) ||
        ((b.p.year || 0) - (a.p.year || 0)) || (b.maxId - a.maxId) ||
        (b.untraced - a.untraced);
    });
    jobs.forEach(function (job, j) {
      job.idx.forEach(function (i) { jobOf[i] = j; });
    });
  }

  // Point halfway along the longest part, as [lat, lng].
  function midpoint(geom) {
    var parts = geom.type === "MultiLineString"
      ? geom.coordinates : [geom.coordinates];
    var best = null, bestLen = -1;
    parts.forEach(function (pts) {
      var len = partLength(pts);
      if (len > bestLen) { bestLen = len; best = pts; }
    });
    if (!best || !best.length) { return null; }
    var half = bestLen / 2, walked = 0;
    for (var k = 1; k < best.length; k++) {
      var d = segLength(best[k - 1], best[k]);
      if (walked + d >= half && d > 0) {
        var t = (half - walked) / d;
        return [best[k - 1][1] + t * (best[k][1] - best[k - 1][1]),
                best[k - 1][0] + t * (best[k][0] - best[k - 1][0])];
      }
      walked += d;
    }
    return [best[0][1], best[0][0]];
  }

  // [south, west, north, east] of a geometry, padded by PAD_M.
  function bounds(geom) {
    var parts = geom.type === "MultiLineString"
      ? geom.coordinates : [geom.coordinates];
    var s = 90, w = 180, n = -90, e = -180;
    parts.forEach(function (pts) {
      pts.forEach(function (p) {
        s = Math.min(s, p[1]); n = Math.max(n, p[1]);
        w = Math.min(w, p[0]); e = Math.max(e, p[0]);
      });
    });
    var dLat = PAD_M / 111320;
    var dLon = PAD_M / (111320 * Math.cos((s + n) / 2 * Math.PI / 180));
    return [s - dLat, w - dLon, n + dLat, e + dLon];
  }

  function partLength(pts) {
    var len = 0;
    for (var k = 1; k < pts.length; k++) { len += segLength(pts[k - 1], pts[k]); }
    return len;
  }

  function segLength(a, b) {
    var dx = (b[0] - a[0]) * Math.cos(a[1] * Math.PI / 180);
    var dy = b[1] - a[1];
    return Math.sqrt(dx * dx + dy * dy);
  }

  // Where each link sends the mapper: openstreetmap.org, iD (with the way
  // the job is about selected), and JOSM remote control (the padded box
  // downloaded, and that way selected).
  function targets(job) {
    var c = job.mid;
    if (!c) { return null; }
    var way = job.way;
    var ll = c[0].toFixed(6) + "/" + c[1].toFixed(6);
    var b = job.bounds;
    return {
      osm: "https://www.openstreetmap.org/#map=19/" + ll,
      id: "https://www.openstreetmap.org/edit?editor=id" +
        (way != null ? "&way=" + encodeURIComponent(way) : "") +
        "#map=19/" + ll,
      josm: JOSM + "?left=" + b[1].toFixed(6) + "&right=" + b[3].toFixed(6) +
        "&top=" + b[2].toFixed(6) + "&bottom=" + b[0].toFixed(6) +
        (way != null ? "&select=way" + encodeURIComponent(way) : "") +
        "&changeset_source=" +
        encodeURIComponent("City of Guelph Bike Facilities"),
    };
  }

  // JOSM listens on loopback; a page served over https may still call it.
  // no-cors: the reply is opaque, but a refused connection still rejects.
  function openJosm(url, link) {
    fetch(url, { mode: "no-cors" }).then(function () {
      flash(link, "sent");
    }, function () {
      flash(link, "JOSM?");
      alert("JOSM did not answer. Start JOSM and enable Preferences > " +
            "Remote Control, then try again.");
    });
  }

  function flash(link, text) {
    if (!link) { return; }
    var old = link.textContent;
    link.textContent = text;
    setTimeout(function () { link.textContent = old; }, 1500);
  }

  function linksHtml(job) {
    var t = targets(job);
    if (!t) { return '<span class="osm-blank">&mdash;</span>'; }
    var h = '<a href="' + esc(t.id) + '" target="_blank" rel="noopener" ' +
      'title="Open here in the iD editor (hotkey: I)">iD</a> &middot; ' +
      '<a href="' + esc(t.josm) + '" class="josm" ' +
      'title="Load this area into JOSM via remote control (hotkey: J)">JOSM</a> &middot; ' +
      '<a href="' + esc(t.osm) + '" target="_blank" rel="noopener" ' +
      'title="View on openstreetmap.org (hotkey: O)">OSM</a>';
    if (job.way != null) {
      h += ' &middot; <a href="https://www.openstreetmap.org/way/' +
        encodeURIComponent(job.way) + '" target="_blank" rel="noopener" ' +
        'title="The OSM way this row is about">way</a>';
    }
    return '<span class="osm-links">' + h + "</span>";
  }

  function facility(p) {
    var bits = [p.type || "facility"];
    if (p.buffer) { bits.push(p.buffer.toLowerCase() + " buffer"); }
    return bits.join(", ");
  }

  function sideNote(p) {
    return p.side === "any"
      ? "side unclear (City line on the centreline)" : "";
  }

  function popupHtml(f, i) {
    var p = f.properties;
    var bits = [];
    if (p.length != null) { bits.push(p.length.toLocaleString() + " m"); }
    if (p.year) { bits.push("installed " + p.year); }
    if (p.id != null) { bits.push("City #" + p.id); }
    var h = "<strong>" + esc(p.street || "(unnamed)") + "</strong><br>" +
      esc(facility(p)) + " &middot; " +
      '<span class="status-' + p.status + '">' + LABELS[p.status] + "</span>" +
      (p.gap ? " (" + esc(LABELS[p.gap] || p.gap) + ")" : "") +
      "<br>" + bits.join(" &middot; ");
    if (p.tag) { h += "<br>Add: <code>" + esc(p.tag) + "</code>"; }
    return h + "<br>" + linksHtml(jobs[jobOf[i]]);
  }

  function buildTable() {
    var tbody = document.querySelector("#gap-table tbody");
    var html = [];
    jobs.forEach(function (job, j) {
      var p = job.p;
      var note = sideNote(p);
      var n = job.idx.length;
      html.push('<tr class="seg" data-j="' + j + '" data-status="' + p.status + '">' +
        '<td class="num">' + (p.year || "&mdash;") + "</td>" +
        '<td class="col-name"><strong>' + esc(p.street || "(unnamed)") +
        "</strong> &middot; " + esc(facility(p)) +
        ' <span class="len">&middot; ' + job.length.toLocaleString() + " m" +
        (n > 1 ? " in " + n + " pieces" : "") + "</span>" +
        (p.tag ? '<br><code class="tag">' + esc(p.tag) + "</code>" : "") +
        (note ? '<br><span class="len">' + esc(note) + "</span>" : "") +
        "</td>" +
        '<td class="status-' + p.status + '">' + LABELS[p.status] +
        (p.gap ? '<br><span class="len">' + esc(LABELS[p.gap] || p.gap) +
          "</span>" : "") + "</td>" +
        "<td>" + linksHtml(job) + "</td></tr>");
    });
    tbody.innerHTML = html.join("");

    tbody.addEventListener("click", function (ev) {
      var a = ev.target.closest("a");
      if (a) {
        if (a.classList.contains("josm")) {
          ev.preventDefault();
          openJosm(a.href, a);
        }
        return;  // let the other links work
      }
      var tr = ev.target.closest("tr");
      if (tr) { select(parseInt(tr.dataset.j, 10), true); }
    });
    // Popups are built on the map, outside the table: same JOSM handling.
    document.getElementById("gap-map").addEventListener("click", function (ev) {
      var a = ev.target.closest && ev.target.closest("a.josm");
      if (a) { ev.preventDefault(); openJosm(a.href, a); }
    });
  }

  // Select a job: thicken its lines, fit the map, open a popup, mark its row.
  // ``i`` is the line that was clicked, when it came from the map.
  function select(j, fromTable, at, i) {
    var job = jobs[j];
    if (!job) { return; }
    if (selectedJob != null) {
      jobs[selectedJob].idx.forEach(function (k) {
        lines[k].setStyle({ weight: WEIGHT });
      });
    }
    selectedJob = j;
    job.idx.forEach(function (k) {
      lines[k].setStyle({ weight: SELECTED_WEIGHT });
      if (map.hasLayer(lines[k])) { lines[k].bringToFront(); }
    });
    if (fromTable) {
      map.fitBounds([[job.bounds[0], job.bounds[1]], [job.bounds[2], job.bounds[3]]],
                    { maxZoom: 18, padding: [40, 40] });
    }
    var line = lines[i != null ? i : job.idx[0]];
    if (map.hasLayer(line)) {
      line.openPopup(at || (job.mid ? L.latLng(job.mid[0], job.mid[1]) : undefined));
    }
    if (selectedRow) { selectedRow.classList.remove("selected"); }
    var tr = document.querySelector('#gap-table tr.seg[data-j="' + j + '"]');
    if (tr) {
      tr.classList.add("selected");
      selectedRow = tr;
      if (!fromTable) { tr.scrollIntoView({ block: "center" }); }
    }
  }

  function wireControls() {
    var boxes = {};
    STATUSES.forEach(function (s) {
      boxes[s] = document.getElementById("show-" + s);
    });
    var filter = document.getElementById("filter");
    var rows = {};
    Array.prototype.forEach.call(
      document.querySelectorAll("#gap-table tr.seg"),
      function (tr) { rows[tr.dataset.j] = tr; });

    function statusOn(status) {
      var b = boxes[status];
      return b ? b.checked : true;
    }

    // A job shows when its status is on and the filter text is empty or
    // found in its street, facility, tag, year, OSM way or any City id.
    function apply() {
      var q = filter.value.trim().toLowerCase();
      jobs.forEach(function (job, j) {
        var p = job.p;
        var ids = job.idx.map(function (i) { return features[i].properties.id; });
        var text = [p.street, p.type, p.buffer, p.tag, p.year, job.way,
                    LABELS[p.status]].concat(ids).join(" ").toLowerCase();
        var hit = statusOn(p.status) && (!q || text.indexOf(q) > -1);
        rows[j].style.display = hit ? "" : "none";
        job.idx.forEach(function (i) {
          var m = lines[i];
          if (hit && !map.hasLayer(m)) { map.addLayer(m); }
          else if (!hit && map.hasLayer(m)) { map.removeLayer(m); }
        });
      });
      if (selectedJob != null) {
        jobs[selectedJob].idx.forEach(function (i) {
          if (map.hasLayer(lines[i])) { lines[i].bringToFront(); }
        });
      }
    }

    STATUSES.forEach(function (k) {
      if (boxes[k]) { boxes[k].addEventListener("change", apply); }
    });
    filter.addEventListener("input", apply);
    apply();

    // I / J / O open the selected job in iD, JOSM or on openstreetmap.org.
    document.addEventListener("keydown", function (ev) {
      if (ev.ctrlKey || ev.metaKey || ev.altKey) { return; }
      if (/^(input|textarea|select)$/i.test(ev.target.tagName)) { return; }
      var key = ev.key.toLowerCase();
      if (["o", "i", "j"].indexOf(key) < 0 || selectedJob == null) { return; }
      var t = targets(jobs[selectedJob]);
      if (!t) { return; }
      ev.preventDefault();
      if (key === "j") {
        openJosm(t.josm, selectedRow && selectedRow.querySelector("a.josm"));
      } else {
        window.open(key === "o" ? t.osm : t.id, "_blank", "noopener");
      }
    });
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  document.addEventListener("DOMContentLoaded", init);
})();
