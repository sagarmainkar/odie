// map.js: the explainer-video kit's offline map. It adds s.map, s.place, s.pin, s.route, s.vehicle, s.along,
// s.project, s.region and s.glow to every scene's helpers (through Video.extend), and runs after video.js and after
// window.__geo, the map's data (Natural Earth, public domain; see README.md): the land, the countries as India sees
// them with the borders between them, India's states with theirs, and about 7,000 populated places.
//
// The projection is Web Mercator. s.map({center, width}) puts `center` in the middle of the 1920x1080 stage with
// `width` degrees of longitude across it, draws the sea, the land and the borders, and keeps that projection for the
// rest of this frame; the other drawing helpers use it (and say "call s.map first" without it). Before every frame
// the projection is forgotten, so a frame never leans on the one drawn before it.
//
// The shapes become canvas paths once, as the page loads, in "Mercator degrees": x is the longitude and y the
// Mercator height of the latitude, in degrees (mercatorY). In those units the projection is only a scale and a shift,
// so a frame draws each shape in view with one transform, and a route's shape is the same at every zoom.
(function () {
  "use strict";

  const W = Video.W;
  const H = Video.H;
  const MAX_LAT = 85.0511;  // Web Mercator's edge: the latitude whose height equals 180 degrees, a square world
  const STATES_BELOW = 15;  // India's states are drawn when the map is fewer degrees across than this
  const LABEL_ROOM = 1.1;  // a country or state is named (labels: true) when its main land is this much wider than
  // its name
  const LABEL_GAP = 10;  // pixels kept clear around each name, so two names never touch
  const FLIGHT_LIFT = 0.08;  // a flight's arc rises this share of its length at the middle
  const ARC_STEPS = 48;  // points along each leg of a flight's great circle
  const HEADING_WINDOW = 0.01;  // a vehicle faces from 1 % of the route behind it to 1 % ahead: turns are smooth
  const STYLES = {
    dark: {sea: "#0e1117", land: "#1d2430", border: "#3a4556", label: Video.colors.text},
    paper: {sea: "#e8e4d8", land: "#f6f3ea", border: "#b8b0a0", label: "#333"},
  };
  const MAP_DEFAULTS = {center: [20, 0], width: 360, style: "dark", opacity: 1, labels: false};
  const PIN_DEFAULTS = {label: "", size: 16, color: Video.colors.red, opacity: 1, side: "right", textSize: 30};
  const ROUTE_DEFAULTS = {kind: "road", color: Video.colors.yellow, width: 5, dash: false, opacity: 1};
  const VEHICLE_DEFAULTS = {size: 56, color: Video.colors.text, opacity: 1};
  const REGION_DEFAULTS = {color: Video.colors.blue, opacity: 1, fill: 0.45, line: 2};
  const GLOW_DEFAULTS = {color: Video.colors.blue, opacity: 0.4, radius: 90};
  const DASH = [18, 14];  // a dashed route's pattern, in pixels

  // ---- Mercator: latitude to height and back, pure maths ----

  // A number kept inside 0..1. clamp01(1.4) -> 1
  function clamp01(x) {
    return Math.min(1, Math.max(0, x));
  }

  // A latitude kept inside what Web Mercator can show. clampLat(89) -> 85.0511; clampLat(27.3) -> 27.3
  function clampLat(lat) {
    return Math.min(MAX_LAT, Math.max(-MAX_LAT, lat));
  }

  // A latitude's Mercator height, in degrees (so a degree of longitude and a degree of height are the same length on
  // the stage). mercatorY(0) -> 0; mercatorY(45) -> 50.5; mercatorY(85.0511) -> 180
  function mercatorY(lat) {
    const phi = clampLat(lat) * Math.PI / 180;
    return Math.log(Math.tan(Math.PI / 4 + phi / 2)) * 180 / Math.PI;
  }

  // The latitude at a Mercator height (the reverse of mercatorY). latitudeAt(50.5) -> 45.0; latitudeAt(0) -> 0
  function latitudeAt(y) {
    return (2 * Math.atan(Math.exp(y * Math.PI / 180)) - Math.PI / 2) * 180 / Math.PI;
  }

  // A longitude difference brought within half a turn, the short way round. wrapDegrees(350) -> -10;
  // wrapDegrees(-190) -> 170; wrapDegrees(20) -> 20
  function wrapDegrees(d) {
    let wrapped = (d + 180) % 360;
    if (wrapped < 0) {
      wrapped += 360;
    }
    return wrapped - 180;
  }

  // ---- The map's data, turned into canvas paths once ----

  // A box around points in Mercator degrees (south and north are Mercator heights, not latitudes), grown point by
  // point: an empty box, then growBox(box, 88, 28.1) and growBox(box, 89, 29.2) -> {west: 88, east: 89, south: 28.1,
  // north: 29.2}
  function emptyBox() {
    return {west: Infinity, east: -Infinity, south: Infinity, north: -Infinity};
  }

  function growBox(box, x, y) {
    box.west = Math.min(box.west, x);
    box.east = Math.max(box.east, x);
    box.south = Math.min(box.south, y);
    box.north = Math.max(box.north, y);
  }

  // One polygon ([outer ring, holes...], each ring [[lon, lat], ...]) as a path in Mercator degrees, with its box.
  function polygonPart(rings) {
    const path = new Path2D();
    const box = emptyBox();
    for (const ring of rings) {
      for (let i = 0; i < ring.length; i++) {
        const x = ring[i][0];
        const y = mercatorY(ring[i][1]);
        if (i === 0) {
          path.moveTo(x, y);
        } else {
          path.lineTo(x, y);
        }
        growBox(box, x, y);
      }
      path.closePath();
    }
    return {path: path, box: box};
  }

  // One border line ([[lon, lat], ...]) as a path in Mercator degrees, with its box.
  function linePart(line) {
    const path = new Path2D();
    const box = emptyBox();
    for (let i = 0; i < line.length; i++) {
      const x = line[i][0];
      const y = mercatorY(line[i][1]);
      if (i === 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
      growBox(box, x, y);
    }
    return {path: path, box: box};
  }

  // The box of the biggest of an area's parts (by box size): its main land, which decides whether its name fits.
  // India -> the mainland's box, not one stretched to the Andaman Islands; Kiribati -> one small atoll's
  function biggestBox(parts) {
    let biggest = parts[0].box;
    for (const part of parts) {
      const size = (part.box.east - part.box.west) * (part.box.north - part.box.south);
      const biggestSize = (biggest.east - biggest.west) * (biggest.north - biggest.south);
      if (size > biggestSize) {
        biggest = part.box;
      }
    }
    return biggest;
  }

  // A file of areas (countries, or India's states) as {areas, borders}: each area {name, names, label, parts, main}
  // (names: its name and other names, lower case, for looking it up; main: its main land's box), and the borders
  // between them as line parts.
  function areasOf(collection) {
    const areas = [];
    const borders = [];
    for (const feature of collection.features) {
      const properties = feature.properties;
      if (properties.borders) {
        for (const line of feature.geometry.coordinates) {
          borders.push(linePart(line));
        }
        continue;
      }
      const names = [properties.name.toLowerCase()];
      if (properties.aliases) {
        for (const alias of properties.aliases) {
          names.push(alias.toLowerCase());
        }
      }
      const parts = feature.geometry.coordinates.map(polygonPart);
      areas.push({name: properties.name, names: names, label: properties.label, parts: parts,
                  main: biggestBox(parts)});
    }
    return {areas: areas, borders: borders};
  }

  // The gazetteer by lower-case name: "pune" -> [18.532, 73.848, "India"]; "hyderabad, pakistan" -> Pakistan's.
  function placeIndexOf(places) {
    const index = new Map();
    for (const name of Object.keys(places)) {
      index.set(name.toLowerCase(), places[name]);
    }
    return index;
  }

  // Everything the map draws, built once from window.__geo (null when the page has no map data).
  function loadGeo(geo) {
    if (!geo) {
      return null;
    }
    const land = [];
    for (const feature of geo.land.features) {
      for (const polygon of feature.geometry.coordinates) {
        land.push(polygonPart(polygon));
      }
    }
    return {land: land, countries: areasOf(geo.countries), states: areasOf(geo.states),
            places: placeIndexOf(geo.places)};
  }

  const shapes = loadGeo(window.__geo);
  let projection = null;  // this frame's, set by s.map; forgotten before every frame

  // Refuses to draw without the map's data on the page (a page put together without page.assemble).
  function needGeo(helper) {
    if (!shapes) {
      throw new Error(`${helper}: the map's data (window.__geo) isn't on this page`);
    }
  }

  // ---- Places: names and [lat, lon] ----

  // The [lat, lon] of a populated place from Natural Earth's gazetteer, or null. Case and spaces don't matter, and a
  // country after a comma is checked: "Pune" -> [18.532, 73.848]; " pune, India " -> the same; "Pune, Nepal" -> null;
  // "Hyderabad" -> India's (the bigger); "Hyderabad, Pakistan" -> Pakistan's; "Lachung" -> null (a village it lacks:
  // the brief gives [lat, lon] for those)
  function place(name) {
    needGeo("s.place");
    if (typeof name !== "string") {
      return null;
    }
    const key = name.trim().toLowerCase();
    const exact = shapes.places.get(key);
    if (exact) {
      return [exact[0], exact[1]];
    }
    const comma = key.lastIndexOf(",");
    if (comma === -1) {
      return null;
    }
    const town = shapes.places.get(key.slice(0, comma).trim());
    const country = key.slice(comma + 1).trim();
    if (town && town[2].toLowerCase() === country) {
      return [town[0], town[1]];
    }
    return null;
  }

  // Where a helper's point is: [lat, lon] as given, or a place's name looked up. [27.3, 88.6] -> [27.3, 88.6];
  // "Gangtok" -> [27.333, 88.617]; "Lachung" -> Error saying to give it as [lat, lon]
  function latLonOf(where, helper) {
    if (Array.isArray(where) && Number.isFinite(where[0]) && Number.isFinite(where[1])) {
      return [where[0], where[1]];
    }
    if (typeof where === "string") {
      const found = place(where);
      if (found) {
        return found;
      }
      throw new Error(`${helper}: no place called "${where}" on the map; give it as [lat, lon]`);
    }
    throw new Error(`${helper}: ${JSON.stringify(where)} isn't a place: give [lat, lon] or a place's name`);
  }

  // ---- The projection ----

  // The projection for a centre and a width: k pixels to a degree, and the centre in Mercator degrees.
  // ([20, 80], 30) -> {k: 64, x0: 80, y0: 20.4, ...}: 80E sits at x 960, and 95E (15 degrees east) at 1920
  function makeProjection(center, width, style) {
    const k = W / width;
    return {k: k, x0: center[1], y0: mercatorY(center[0]), width: width, style: style};
  }

  // The view in Mercator degrees: what the stage shows. Centred on 80E at 30 degrees across -> west 65, east 95.
  function viewOf(pr) {
    return {west: pr.x0 - W / 2 / pr.k, east: pr.x0 + W / 2 / pr.k,
            south: pr.y0 - H / 2 / pr.k, north: pr.y0 + H / 2 / pr.k};
  }

  // A point in Mercator degrees as stage pixels (x as given: no wrapping). (80, 20.4) centred there -> [960, 540]
  function toPixels(pr, x, y) {
    return [W / 2 + (x - pr.x0) * pr.k, H / 2 - (y - pr.y0) * pr.k];
  }

  // The frame's projection, or an error saying to draw the map first. needProjection("s.pin") before s.map -> Error
  function needProjection(helper) {
    if (!projection) {
      throw new Error(`${helper} draws on the map: call s.map first in this frame`);
    }
    return projection;
  }

  // A place's pixels on the stage, the short way round the world from the centre (a point 350 degrees east is
  // drawn 10 degrees west); `helper` names who asked, for an unknown place. Centred on Gangtok: "Gangtok" -> [960, 540]
  function pixelsOf(pr, where, helper) {
    const latLon = latLonOf(where, helper);
    const x = pr.x0 + wrapDegrees(latLon[1] - pr.x0);
    return toPixels(pr, x, mercatorY(latLon[0]));
  }

  // A place's pixels on this frame's map, for custom drawing. s.map({center: "Gangtok", width: 6});
  // s.project("Gangtok") -> [960, 540]; s.project([27.33, 89.62]) -> about [1280, 540] (a degree east is 320 px)
  function project(where) {
    const pr = needProjection("s.project");
    return pixelsOf(pr, where, "s.project");
  }

  // Whether a box (Mercator degrees, moved `shift` degrees east) overlaps the view: what is drawn, the rest skipped.
  // A box over Sikkim with the view on Gangtok -> true; the same box with the view on Brazil -> false
  function inView(box, shift, view) {
    return box.east + shift >= view.west && box.west + shift <= view.east &&
      box.north >= view.south && box.south <= view.north;
  }

  // Draws every part in view, in Mercator degrees, with `draw(path)` under the frame's transform. A part is looked
  // at where it is and a turn of the world east and west, so the map works across the 180th meridian.
  function eachInView(ctx, pr, parts, draw) {
    const view = viewOf(pr);
    for (const shift of [-360, 0, 360]) {
      ctx.save();
      ctx.transform(pr.k, 0, 0, -pr.k, W / 2 + (shift - pr.x0) * pr.k, H / 2 + pr.y0 * pr.k);
      for (const part of parts) {
        if (inView(part.box, shift, view)) {
          draw(part.path);
        }
      }
      ctx.restore();
    }
  }

  // ---- s.map: the sea, the land, the borders and the names ----

  // The style called name. "dark" -> its colours; "neon" -> Error naming the two
  function styleCalled(name) {
    const style = STYLES[name];
    if (!style) {
      throw new Error(`s.map: style "${name}" isn't "dark" or "paper"`);
    }
    return style;
  }

  // Refuses a width the map can't show: more than 0 and at most 360 degrees of longitude across the stage.
  // 30 -> fine; 0 or 400 -> Error
  function checkWidth(width) {
    const fine = Number.isFinite(width) && width > 0 && width <= 360;
    if (!fine) {
      throw new Error(`s.map: width ${width} isn't between 0 and 360 (degrees of longitude across the stage)`);
    }
  }

  // Whether India's states are drawn: when the map is zoomed in to fewer than 15 degrees across.
  // width 6 (Sikkim and around) -> true; width 30 (all of India) -> false
  function showsStates(width) {
    return width < STATES_BELOW;
  }

  // The size of an area's main land in square Mercator degrees, for naming the biggest first.
  function mainSize(area) {
    return (area.main.east - area.main.west) * (area.main.north - area.main.south);
  }

  // Whether two name boxes ({x, y, w, h}, pixels) come within LABEL_GAP of each other.
  // {0, 0, 100, 20} and {105, 0, 50, 20} -> true (5 px apart); and {200, 0, 50, 20} -> false
  function crowded(a, b) {
    const apartX = a.x - LABEL_GAP >= b.x + b.w || b.x - LABEL_GAP >= a.x + a.w;
    const apartY = a.y - LABEL_GAP >= b.y + b.h || b.y - LABEL_GAP >= a.y + a.h;
    return !(apartX || apartY);
  }

  // Names the areas whose main land is wider on the stage than their name, at their label points, biggest first; a
  // name that would crowd one already written is left out. `taken` is the boxes written so far (states after
  // countries share it). At the world view: Russia and Canada are named, Portugal (narrower than "PORTUGAL") isn't.
  function labelAreas(ctx, pr, areas, size, taken) {
    const view = viewOf(pr);
    const biggestFirst = areas.slice().sort(function (a, b) {
      return mainSize(b) - mainSize(a);
    });
    ctx.save();
    ctx.fillStyle = pr.style.label;
    ctx.globalAlpha = ctx.globalAlpha * 0.75;
    ctx.font = `600 ${size}px ${Video.SANS}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const area of biggestFirst) {
      const name = area.name.toUpperCase();
      const textWidth = ctx.measureText(name).width;
      const across = (area.main.east - area.main.west) * pr.k;
      if (across < textWidth * LABEL_ROOM) {
        continue;
      }
      const x = pr.x0 + wrapDegrees(area.label[0] - pr.x0);
      const y = mercatorY(area.label[1]);
      if (x < view.west || x > view.east || y < view.south || y > view.north) {
        continue;
      }
      const at = toPixels(pr, x, y);
      const box = {x: at[0] - textWidth / 2, y: at[1] - size / 2, w: textWidth, h: size};
      const clash = taken.some(function (other) {
        return crowded(box, other);
      });
      if (clash) {
        continue;
      }
      taken.push(box);
      ctx.fillText(name, at[0], at[1]);
    }
    ctx.restore();
  }

  // The map for this frame, and the projection everything after it on the map uses. Options: center ([lat, lon] or a
  // place's name; [20, 0] by default), width (degrees of longitude across the stage, 360 the whole world; default 360),
  // style ("dark" or "paper"), opacity, labels (false; true names the countries, and the states once zoomed in).
  // India's states are drawn below 15 degrees across. A flight that zooms in on the plane:
  // s.map({center: s.along(["Pune", "Siliguri"], p, {kind: "flight"}), width: s.lerp(30, 4, p)})
  function map(ctx, options) {
    needGeo("s.map");
    const o = Object.assign({}, MAP_DEFAULTS, options);
    const style = styleCalled(o.style);
    checkWidth(o.width);
    const center = latLonOf(o.center, "s.map");
    const pr = makeProjection(center, o.width, style);
    projection = pr;
    if (o.opacity <= 0) {
      return;
    }
    ctx.save();
    ctx.globalAlpha = ctx.globalAlpha * clamp01(o.opacity);
    ctx.fillStyle = style.sea;
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = style.land;
    eachInView(ctx, pr, shapes.land, function (path) {
      ctx.fill(path, "evenodd");
    });
    ctx.strokeStyle = style.border;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.lineWidth = 1.6 / pr.k;
    eachInView(ctx, pr, shapes.countries.borders, function (path) {
      ctx.stroke(path);
    });
    const states = showsStates(o.width);
    if (states) {
      ctx.lineWidth = 1 / pr.k;
      ctx.setLineDash([6 / pr.k, 5 / pr.k]);
      eachInView(ctx, pr, shapes.states.borders, function (path) {
        ctx.stroke(path);
      });
      ctx.setLineDash([]);
    }
    if (o.labels) {
      const taken = [];
      labelAreas(ctx, pr, shapes.countries.areas, 24, taken);
      if (states) {
        labelAreas(ctx, pr, shapes.states.areas, 18, taken);
      }
    }
    ctx.restore();
  }

  // ---- Areas: a country or an Indian state, filled ----

  // The country (or Indian state) called name, by any of its names, any case. "india" -> India; "Sikkim" -> Sikkim;
  // "United States of America" -> United States; "Atlantis" -> Error
  function areaCalled(name) {
    const key = String(name).trim().toLowerCase();
    for (const area of shapes.countries.areas) {
      if (area.names.includes(key)) {
        return area;
      }
    }
    for (const area of shapes.states.areas) {
      if (area.names.includes(key)) {
        return area;
      }
    }
    throw new Error(`s.region: no country or Indian state called ${name} on the map (modern borders only; for a ` +
                    "past kingdom use s.glow around its places)");
  }

  // A modern country or Indian state, filled and outlined. Options: color (s.colors.blue), opacity (1, the whole),
  // fill (0.45, how strong the fill is under the outline), line (2: the outline's pixels; 0 for none).
  // s.region("Sikkim", {color: s.colors.green, opacity: s.fade(t, 1)})
  function region(ctx, name, options) {
    const pr = needProjection("s.region");
    const o = Object.assign({}, REGION_DEFAULTS, options);
    const area = areaCalled(name);
    if (o.opacity <= 0) {
      return;
    }
    ctx.save();
    ctx.globalAlpha = ctx.globalAlpha * clamp01(o.opacity);
    ctx.fillStyle = o.color;
    ctx.strokeStyle = o.color;
    ctx.lineJoin = "round";
    ctx.lineWidth = o.line / pr.k;
    const fillAlpha = ctx.globalAlpha * clamp01(o.fill);
    const lineAlpha = ctx.globalAlpha;
    eachInView(ctx, pr, area.parts, function (path) {
      ctx.globalAlpha = fillAlpha;
      ctx.fill(path, "evenodd");
      if (o.line > 0) {
        ctx.globalAlpha = lineAlpha;
        ctx.stroke(path);
      }
    });
    ctx.restore();
  }

  // ---- Glow: a soft light around a group of places (a kingdom, a trade route, a region of a story) ----

  let glowCanvas = null;  // a stage-sized scratch canvas, made the first time a glow is drawn and cleared each use

  // The convex hull of points (the smallest convex outline around them), by Andrew's monotone chain.
  // [[0, 0], [2, 0], [1, 1], [1, 3], [0, 2]] -> [[0, 0], [2, 0], [1, 3], [0, 2]] ((1, 1) is inside)
  function hull(points) {
    const sorted = points.slice().sort(function (a, b) {
      return a[0] - b[0] || a[1] - b[1];
    });
    if (sorted.length < 3) {
      return sorted;
    }
    // Which way o -> a -> b turns: more than 0 left (anticlockwise), 0 straight on, less than 0 right.
    function cross(o, a, b) {
      return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    }
    const lower = [];
    for (const p of sorted) {
      while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
        lower.pop();
      }
      lower.push(p);
    }
    const upper = [];
    for (const p of sorted.slice().reverse()) {
      while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
        upper.pop();
      }
      upper.push(p);
    }
    lower.pop();
    upper.pop();
    return lower.concat(upper);
  }

  // A soft glow around a group of places: the outline around them all, widened by `radius` pixels and blurred.
  // Options: color (s.colors.blue), opacity (0.4), radius (90 pixels). One place gives a soft disc.
  // s.glow(["Delhi", "Agra", "Lahore"], {opacity: 0.4 * s.fade(t, 1)})
  function glow(ctx, places, options) {
    const pr = needProjection("s.glow");
    const o = Object.assign({}, GLOW_DEFAULTS, options);
    if (!Array.isArray(places) || places.length === 0) {
      throw new Error("s.glow: give a list of places, [lat, lon] or names");
    }
    const points = places.map(function (where) {
      return pixelsOf(pr, where, "s.glow");
    });
    if (o.opacity <= 0) {
      return;
    }
    if (!glowCanvas) {
      glowCanvas = document.createElement("canvas");
      glowCanvas.width = W;
      glowCanvas.height = H;
    }
    const scratch = glowCanvas.getContext("2d");
    scratch.reset();
    scratch.fillStyle = o.color;
    scratch.strokeStyle = o.color;
    scratch.lineWidth = o.radius * 2;
    scratch.lineJoin = "round";
    scratch.lineCap = "round";
    const outline = hull(points);
    scratch.beginPath();
    for (let i = 0; i < outline.length; i++) {
      if (i === 0) {
        scratch.moveTo(outline[i][0], outline[i][1]);
      } else {
        scratch.lineTo(outline[i][0], outline[i][1]);
      }
    }
    scratch.closePath();
    scratch.fill();
    scratch.stroke();
    for (const point of points) {
      scratch.beginPath();
      scratch.arc(point[0], point[1], o.radius, 0, Math.PI * 2);
      scratch.fill();
    }
    ctx.save();
    ctx.globalAlpha = ctx.globalAlpha * clamp01(o.opacity);
    ctx.filter = `blur(${o.radius / 2}px)`;
    ctx.drawImage(glowCanvas, 0, 0);
    ctx.restore();
  }

  // ---- Pins ----

  // A dot at a place, with its name beside it. Options: label (none by default), size (the dot's width, 16 px),
  // color (s.colors.red), opacity, side ("right", "left", "above" or "below": where the label sits), textSize (30).
  // Returns the dot's pixels. s.pin("Gangtok", {label: "Gangtok", opacity: s.fade(t, 1)})
  function pin(ctx, where, options) {
    const pr = needProjection("s.pin");
    const o = Object.assign({}, PIN_DEFAULTS, options);
    const at = pixelsOf(pr, where, "s.pin");
    if (o.opacity <= 0) {
      return at;
    }
    const radius = o.size / 2;
    ctx.save();
    ctx.globalAlpha = ctx.globalAlpha * clamp01(o.opacity);
    ctx.beginPath();
    ctx.arc(at[0], at[1], radius, 0, Math.PI * 2);
    ctx.fillStyle = o.color;
    ctx.fill();
    ctx.lineWidth = 3;
    ctx.strokeStyle = pr.style.sea;
    ctx.stroke();
    if (o.label) {
      drawPinLabel(ctx, pr, at, radius, o);
    }
    ctx.restore();
    return at;
  }

  // A pin's name, on the side the options say, a little away from the dot. side "right" -> left-aligned just past it
  function drawPinLabel(ctx, pr, at, radius, o) {
    const gap = radius + 12;
    ctx.font = `500 ${o.textSize}px ${Video.SANS}`;
    ctx.fillStyle = pr.style.label;
    ctx.textBaseline = "middle";
    if (o.side === "right") {
      ctx.textAlign = "left";
      ctx.fillText(o.label, at[0] + gap, at[1]);
    } else if (o.side === "left") {
      ctx.textAlign = "right";
      ctx.fillText(o.label, at[0] - gap, at[1]);
    } else if (o.side === "above") {
      ctx.textAlign = "center";
      ctx.fillText(o.label, at[0], at[1] - gap - o.textSize / 2);
    } else if (o.side === "below") {
      ctx.textAlign = "center";
      ctx.fillText(o.label, at[0], at[1] + gap + o.textSize / 2);
    } else {
      throw new Error(`s.pin: side "${o.side}" isn't one of right, left, above, below`);
    }
  }

  // ---- Routes: the line through places, in Mercator degrees, the same at every zoom ----

  // A point on the great circle from a to b ([lat, lon]) at share u of the way. (equator 0E, equator 90E, 0.5) ->
  // [0, 45]; (Pune, Siliguri, 0) -> Pune
  function greatCircle(a, b, u) {
    const toRad = Math.PI / 180;
    const lat1 = a[0] * toRad;
    const lon1 = a[1] * toRad;
    const lat2 = b[0] * toRad;
    const lon2 = b[1] * toRad;
    const p1 = [Math.cos(lat1) * Math.cos(lon1), Math.cos(lat1) * Math.sin(lon1), Math.sin(lat1)];
    const p2 = [Math.cos(lat2) * Math.cos(lon2), Math.cos(lat2) * Math.sin(lon2), Math.sin(lat2)];
    const dot = Math.min(1, Math.max(-1, p1[0] * p2[0] + p1[1] * p2[1] + p1[2] * p2[2]));
    const angle = Math.acos(dot);
    if (angle < 1e-9) {
      return [a[0], a[1]];
    }
    const w1 = Math.sin((1 - u) * angle) / Math.sin(angle);
    const w2 = Math.sin(u * angle) / Math.sin(angle);
    const x = w1 * p1[0] + w2 * p2[0];
    const y = w1 * p1[1] + w2 * p2[1];
    const z = w1 * p1[2] + w2 * p2[2];
    return [Math.atan2(z, Math.hypot(x, y)) / toRad, Math.atan2(y, x) / toRad];
  }

  // A leg of a flight in Mercator degrees: the great circle from a to b, lifted at its middle by 8 % of its length
  // (towards the top of the map; a leg straight north-south bows west). Each longitude is taken the short way from
  // the point before, so a flight across the 180th meridian doesn't jump. Pune to Delhi -> 49 points, about 11.3
  // Mercator degrees end to end, the middle one lifted 0.9 degrees (8 %) off the great circle, towards the north
  function flightLeg(a, b, startX) {
    const points = [];
    let x = startX;
    let lastLon = a[1];
    for (let i = 0; i <= ARC_STEPS; i++) {
      const latLon = greatCircle(a, b, i / ARC_STEPS);
      x += wrapDegrees(latLon[1] - lastLon);
      lastLon = latLon[1];
      points.push([x, mercatorY(latLon[0])]);
    }
    const first = points[0];
    const last = points[points.length - 1];
    const dx = last[0] - first[0];
    const dy = last[1] - first[1];
    const length = Math.hypot(dx, dy);
    if (length === 0) {
      return points;
    }
    let normal = [-dy / length, dx / length];  // at right angles to the leg
    if (normal[1] < 0) {
      normal = [-normal[0], -normal[1]];  // the side towards the top of the map
    }
    for (let i = 0; i < points.length; i++) {
      const lift = FLIGHT_LIFT * length * Math.sin(Math.PI * i / ARC_STEPS);
      points[i] = [points[i][0] + normal[0] * lift, points[i][1] + normal[1] * lift];
    }
    return points;
  }

  // Refuses a route kind other than "road" or "flight". "flight" -> fine; "sail" -> Error naming both
  function checkKind(kind, helper) {
    if (kind !== "road" && kind !== "flight") {
      throw new Error(`${helper}: kind "${kind}" isn't "road" (straight through the points) or "flight" (great ` +
                      "circles, lifted)");
    }
  }

  // A route's whole line in Mercator degrees: "road" straight through the points, "flight" a lifted great circle
  // for each leg. Longitudes run on the short way from point to point. (["Pune", "Delhi"], "road") -> two points;
  // (["Pune", "Delhi", "Gangtok"], "flight") -> 97 points (two legs of 49 sharing Delhi)
  function routeLine(points, kind, helper) {
    checkKind(kind, helper);
    if (!Array.isArray(points) || points.length < 2) {
      throw new Error(`${helper}: a route needs two places or more, [lat, lon] or names`);
    }
    const stops = points.map(function (where) {
      return latLonOf(where, helper);
    });
    const line = [[stops[0][1], mercatorY(stops[0][0])]];
    for (let i = 1; i < stops.length; i++) {
      const from = line[line.length - 1];
      if (kind === "flight") {
        const leg = flightLeg(stops[i - 1], stops[i], from[0]);
        for (let j = 1; j < leg.length; j++) {
          line.push(leg[j]);
        }
      } else {
        const x = from[0] + wrapDegrees(stops[i][1] - stops[i - 1][1]);
        line.push([x, mercatorY(stops[i][0])]);
      }
    }
    return line;
  }

  // The running length at every point of a line. [[0, 0], [3, 4], [3, 6]] -> [0, 5, 7]
  function runningLengths(line) {
    const lengths = [0];
    for (let i = 1; i < line.length; i++) {
      const step = Math.hypot(line[i][0] - line[i - 1][0], line[i][1] - line[i - 1][1]);
      lengths.push(lengths[i - 1] + step);
    }
    return lengths;
  }

  // The point share p of the way along a line (by length), and the index of the segment it is on.
  // [[0, 0], [4, 0]] at 0.5 -> {point: [2, 0], segment: 0}; [[0, 0], [3, 4], [3, 6]] at 1 -> {point: [3, 6], ...}
  function pointAt(line, lengths, p) {
    const total = lengths[lengths.length - 1];
    const goal = clamp01(p) * total;
    for (let i = 1; i < line.length; i++) {
      if (lengths[i] >= goal) {
        const step = lengths[i] - lengths[i - 1];
        let u = 0;
        if (step > 0) {
          u = (goal - lengths[i - 1]) / step;
        }
        const x = line[i - 1][0] + (line[i][0] - line[i - 1][0]) * u;
        const y = line[i - 1][1] + (line[i][1] - line[i - 1][1]) * u;
        return {point: [x, y], segment: i - 1};
      }
    }
    return {point: line[line.length - 1], segment: line.length - 2};
  }

  // A line drawn to share p of its length: the points up to there, then the point at p.
  // [[0, 0], [4, 0], [4, 4]] at 0.75 -> [[0, 0], [4, 0], [4, 2]]
  function lineUpTo(line, lengths, p) {
    const at = pointAt(line, lengths, p);
    const part = line.slice(0, at.segment + 1);
    part.push(at.point);
    return part;
  }

  // How far east (a whole number of turns, in degrees) a route is moved so its start is on the frame's side of the
  // world. A route starting at 170W (x -170) with the map centred on 170E -> 360 (drawn at 190E, 20 degrees east of
  // the centre); a route starting at 73E with the map on 80E -> 0
  function shiftFor(pr, x) {
    const nearCentre = pr.x0 + wrapDegrees(x - pr.x0);
    return nearCentre - x;
  }

  // A line in Mercator degrees as stage pixels, moved a whole turn if that brings its start nearer the centre.
  function linePixels(pr, line) {
    const shift = shiftFor(pr, line[0][0]);
    return line.map(function (point) {
      return toPixels(pr, point[0] + shift, point[1]);
    });
  }

  // The dash pattern for a route's `dash` option. false -> [] (solid); true -> [18, 14]; [6, 6] -> [6, 6]
  function dashFor(dash) {
    if (dash === true) {
      return DASH;
    }
    if (Array.isArray(dash)) {
      return dash;
    }
    return [];
  }

  // A route through places, drawn to progress p (0 nothing, 1 all of it). Options: kind ("road", straight through the
  // points; "flight", a great circle for each leg, lifted 8 % of its length at the middle), color (s.colors.yellow),
  // width (5 px), dash (false; true for dashes, or a pattern like [6, 6]), opacity. Returns the tip's pixels.
  // s.route(["Pune", "Delhi"], s.at(t, 1, 5), {kind: "flight", dash: true})
  function route(ctx, points, p, options) {
    const pr = needProjection("s.route");
    const o = Object.assign({}, ROUTE_DEFAULTS, options);
    const line = routeLine(points, o.kind, "s.route");
    const drawn = linePixels(pr, lineUpTo(line, runningLengths(line), p));
    const tip = drawn[drawn.length - 1];
    if (o.opacity <= 0 || clamp01(p) <= 0) {
      return tip;
    }
    ctx.save();
    ctx.globalAlpha = ctx.globalAlpha * clamp01(o.opacity);
    ctx.strokeStyle = o.color;
    ctx.lineWidth = o.width;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.setLineDash(dashFor(o.dash));
    ctx.beginPath();
    for (let i = 0; i < drawn.length; i++) {
      if (i === 0) {
        ctx.moveTo(drawn[i][0], drawn[i][1]);
      } else {
        ctx.lineTo(drawn[i][0], drawn[i][1]);
      }
    }
    ctx.stroke();
    ctx.restore();
    return tip;
  }

  // The kind of route a vehicle follows when the options don't say: a plane flies, everything else goes by road.
  // ("plane", {}) -> "flight"; ("car", {}) -> "road"; ("plane", {kind: "road"}) -> "road"
  function vehicleRouteKind(kind, options) {
    if (options && options.kind) {
      return options.kind;
    }
    if (kind === "plane") {
      return "flight";
    }
    return "road";
  }

  // Where a route is at progress p, as [lat, lon]: for a camera that follows a vehicle. Options: kind, as s.route
  // ("road" unless given; give the vehicle's route options so the camera and the vehicle agree).
  // s.along(["Pune", "Delhi"], 0.5) -> about [23.6, 75.5]; s.map({center: s.along(points, p, o), width: 8})
  function along(points, p, options) {
    let kind = ROUTE_DEFAULTS.kind;
    if (options && options.kind) {
      kind = options.kind;
    }
    const line = routeLine(points, kind, "s.along");
    const at = pointAt(line, runningLengths(line), p).point;
    return [latitudeAt(at[1]), wrapDegrees(at[0])];
  }

  // ---- Vehicles: glyphs drawn with paths, nose to the right (+x), one unit long, turned along the route ----

  // A plane from above: a long body, swept wings, a small tail.
  function planeGlyph(ctx) {
    ctx.beginPath();
    ctx.moveTo(0.5, 0);
    ctx.quadraticCurveTo(0.48, -0.06, 0.38, -0.06);
    ctx.lineTo(0.12, -0.06);
    ctx.lineTo(-0.12, -0.48);
    ctx.lineTo(-0.22, -0.48);
    ctx.lineTo(-0.08, -0.06);
    ctx.lineTo(-0.34, -0.05);
    ctx.lineTo(-0.44, -0.2);
    ctx.lineTo(-0.5, -0.2);
    ctx.lineTo(-0.46, -0.03);
    ctx.lineTo(-0.5, 0);
    ctx.lineTo(-0.46, 0.03);
    ctx.lineTo(-0.5, 0.2);
    ctx.lineTo(-0.44, 0.2);
    ctx.lineTo(-0.34, 0.05);
    ctx.lineTo(-0.08, 0.06);
    ctx.lineTo(-0.22, 0.48);
    ctx.lineTo(-0.12, 0.48);
    ctx.lineTo(0.12, 0.06);
    ctx.lineTo(0.38, 0.06);
    ctx.quadraticCurveTo(0.48, 0.06, 0.5, 0);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }

  // A car from above: a rounded body with a windscreen at the front and a rear window.
  function carGlyph(ctx, style) {
    ctx.beginPath();
    ctx.roundRect(-0.5, -0.24, 1, 0.48, 0.12);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = style.sea;
    ctx.beginPath();
    ctx.roundRect(0.1, -0.18, 0.16, 0.36, 0.04);
    ctx.roundRect(-0.36, -0.17, 0.1, 0.34, 0.03);
    ctx.fill();
  }

  // A train from above: a long engine with a rounded nose and a band where its cab is, then a coach.
  function trainGlyph(ctx, style) {
    ctx.beginPath();
    ctx.moveTo(-0.6, -0.16);
    ctx.lineTo(0.38, -0.16);
    ctx.quadraticCurveTo(0.6, -0.16, 0.6, 0);
    ctx.quadraticCurveTo(0.6, 0.16, 0.38, 0.16);
    ctx.lineTo(-0.6, 0.16);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = style.sea;
    ctx.fillRect(0.3, -0.12, 0.08, 0.24);  // the cab's window
    ctx.fillRect(-0.12, -0.16, 0.04, 0.32);  // the gap between engine and coach
  }

  // A walker: a dot with an arrowhead in front, the way a map shows "you are here" heading somewhere.
  function walkerGlyph(ctx) {
    ctx.beginPath();
    ctx.arc(-0.06, 0, 0.26, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0.5, 0);
    ctx.lineTo(0.24, -0.2);
    ctx.lineTo(0.24, 0.2);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }

  const GLYPHS = {plane: planeGlyph, car: carGlyph, train: trainGlyph, walker: walkerGlyph};

  // A vehicle at progress p along a route, its nose along the way it is going. kind: "plane", "car", "train" or
  // "walker". Options: size (56 px long), color (s.colors.text), opacity, kind of route ("flight" for a plane and
  // "road" for the rest unless given; give the same options as the route's so they agree). Returns {x, y, angle}:
  // its pixels and its heading in degrees clockwise from east (0 east, 90 south on the stage, -90 north).
  // s.vehicle("plane", ["Pune", "Delhi"], s.at(t, 1, 5)) -> {x: 840, y: 610, angle: -55}
  function vehicle(ctx, kind, points, p, options) {
    const pr = needProjection("s.vehicle");
    const glyph = GLYPHS[kind];
    if (!glyph) {
      throw new Error(`s.vehicle: kind "${kind}" isn't one of plane, car, train, walker`);
    }
    const o = Object.assign({}, VEHICLE_DEFAULTS, options);
    const line = routeLine(points, vehicleRouteKind(kind, options), "s.vehicle");
    const lengths = runningLengths(line);
    const shift = shiftFor(pr, line[0][0]);
    const here = pointAt(line, lengths, p).point;
    const behind = pointAt(line, lengths, clamp01(p) - HEADING_WINDOW).point;
    const ahead = pointAt(line, lengths, clamp01(p) + HEADING_WINDOW).point;
    const at = toPixels(pr, here[0] + shift, here[1]);
    const back = toPixels(pr, behind[0] + shift, behind[1]);
    const front = toPixels(pr, ahead[0] + shift, ahead[1]);
    const angle = Math.atan2(front[1] - back[1], front[0] - back[0]);
    const result = {x: at[0], y: at[1], angle: angle * 180 / Math.PI};
    if (o.opacity <= 0) {
      return result;
    }
    ctx.save();
    ctx.globalAlpha = ctx.globalAlpha * clamp01(o.opacity);
    ctx.translate(at[0], at[1]);
    ctx.rotate(angle);
    ctx.scale(o.size, o.size);
    ctx.fillStyle = o.color;
    ctx.strokeStyle = pr.style.sea;  // a thin edge in the sea's colour, so the glyph reads over the land and a route
    ctx.lineWidth = 2 / o.size;
    ctx.lineJoin = "round";
    glyph(ctx, pr.style);
    ctx.restore();
    return result;
  }

  // ---- Every scene's s gets the map's helpers; every frame starts without a projection ----

  Video.extend({
    helpers: function (s) {
      s.map = function (o) {
        return map(s.ctx, o);
      };
      s.place = place;
      s.project = project;
      s.along = along;
      s.pin = function (where, o) {
        return pin(s.ctx, where, o);
      };
      s.route = function (points, p, o) {
        return route(s.ctx, points, p, o);
      };
      s.vehicle = function (kind, points, p, o) {
        return vehicle(s.ctx, kind, points, p, o);
      };
      s.region = function (name, o) {
        return region(s.ctx, name, o);
      };
      s.glow = function (places, o) {
        return glow(s.ctx, places, o);
      };
    },
    beforeFrame: function () {
      projection = null;
    },
  });
})();
