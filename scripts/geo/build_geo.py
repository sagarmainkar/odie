"""Builds the offline map's data for the explainer-video kit (odie/video/kit/geo/) from Natural Earth, which is in the
public domain (https://www.naturalearthdata.com/about/terms-of-use/).

Run it once, with the network: uv run --with pyshp python scripts/geo/build_geo.py
pyshp reads the shapefiles; it is not one of Odie's dependencies, so uv brings it in for this run only. The zips are
kept in the system's temp folder (or --downloads DIR), never in the repo; only the four JSON files it writes are
committed. It prints each file's size and the Natural Earth version each came from.

What it writes (coordinates as [lon, lat] in GeoJSON, rounded to 3 decimals, about 100 m):
- land.json: the land, 1:50m, as polygons.
- countries.json: the countries, 1:10m, Natural Earth's "India point of view" file, as polygons with `name` (plus
  `aliases` when Natural Earth has other names, and `label`, where a name sits), and one feature `"borders": true`
  holding the land borders between countries as lines, each drawn once.
- states-in.json: India's states and union territories, 1:10m, the same way (polygons with `name`, and the borders
  between states as lines).
- places.json: Natural Earth's populated places (about 7,300), {"Gangtok": [27.333, 88.617, "India"], ...}: name ->
  [lat, lon, country]. Where two places share a name the bigger one has the plain name and the others are keyed
  "Hyderabad, Pakistan".

Shapes are simplified with Douglas-Peucker at the tolerances below (in degrees), chosen to keep the four files under
3 MB together. Borders are found before simplifying, as the edges two countries share, so each is simplified once and
neighbours never draw two slightly different lines."""
import argparse
import io
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import shapefile

SOURCE = "https://naciscdn.org/naturalearth/"
LAND = "50m/physical/ne_50m_land.zip"
COUNTRIES = "10m/cultural/ne_10m_admin_0_countries_ind.zip"  # "India point of view": only made at 1:10m
STATES = "10m/cultural/ne_10m_admin_1_states_provinces.zip"
PLACES = "10m/cultural/ne_10m_populated_places_simple.zip"

OUT = Path(__file__).resolve().parents[2] / "odie" / "video" / "kit" / "geo"
LIMIT = 3_000_000  # bytes, the four files together

# Douglas-Peucker tolerances in degrees (0.01 degrees is about 1.1 km): how far a simplified line may stray.
LAND_TOLERANCE = 0.02
COUNTRY_TOLERANCE = 0.05     # the polygons, used only to fill a country with s.region
BORDER_TOLERANCE = 0.01      # the lines drawn between countries, seen when zoomed in
STATE_TOLERANCE = 0.006      # India's states, polygons and lines, seen at a few degrees across
DECIMALS = 3


def download(path: str, folder: Path) -> bytes:
    """The zip at Natural Earth's `path`, fetched once into `folder` and read from there after that."""
    saved = folder / Path(path).name
    if not saved.exists():
        print(f"fetching {SOURCE}{path}")
        with urllib.request.urlopen(SOURCE + path, timeout=120) as response:
            saved.write_bytes(response.read())
    return saved.read_bytes()


def member(archive: zipfile.ZipFile, ending: str) -> io.BytesIO:
    """The one file in the zip whose name ends with `ending`, read into memory (nothing is unpacked on disk)."""
    for name in archive.namelist():
        if name.endswith(ending):
            return io.BytesIO(archive.read(name))
    raise FileNotFoundError(f"no *{ending} in the zip")


def read_zip(data: bytes) -> tuple[shapefile.Reader, str]:
    """The shapefile inside a Natural Earth zip, and the version it says it is (its VERSION.txt, e.g. "5.1.1")."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    reader = shapefile.Reader(shp=member(archive, ".shp"), shx=member(archive, ".shx"), dbf=member(archive, ".dbf"),
                              encoding="utf-8")
    version = member(archive, "VERSION.txt").read().decode("ascii").strip()
    return reader, version


def distance_to_segment(p: tuple, a: tuple, b: tuple) -> float:
    """How far point p is from the segment a-b (or from a, when a and b are the same point), in degrees.
    p (1, 1), segment (0, 0)-(2, 0) -> 1.0; p (3, 0), same segment -> 1.0 (past its end, so from (2, 0));
    p (3, 4), segment (0, 0)-(0, 0) -> 5.0."""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5
    share = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_squared
    share = min(1.0, max(0.0, share))
    nearest_x = a[0] + share * dx
    nearest_y = a[1] + share * dy
    return ((p[0] - nearest_x) ** 2 + (p[1] - nearest_y) ** 2) ** 0.5


def douglas_peucker(points: list, tolerance: float) -> list:
    """The line with only the points it needs to stay within `tolerance` of the original. It keeps both ends; between
    two kept points it finds the point farthest from the straight line joining them: if that is farther than the
    tolerance, it is kept and both halves are looked at again; if not, everything between is dropped.
    [(0, 0), (1, 0.1), (2, 0), (3, 2), (4, 0)] with tolerance 0.5 -> [(0, 0), (2, 0), (3, 2), (4, 0)]:
    between (0, 0) and (4, 0) the farthest is (3, 2), 2 off, so it stays; between (0, 0) and (3, 2) the farthest is
    (2, 0), 1.11 off, so it stays; between (0, 0) and (2, 0) only (1, 0.1) is left, 0.1 off, so it goes.
    A closed ring (first point = last) works too: its first "line" is a single point, so the point farthest from it
    is kept first."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(points) - 1)]  # pairs of kept points still to look between; a stack, not recursion (long rings)
    while stack:
        first, last = stack.pop()
        farthest = -1
        farthest_distance = 0.0
        for i in range(first + 1, last):
            distance = distance_to_segment(points[i], points[first], points[last])
            if distance > farthest_distance:
                farthest = i
                farthest_distance = distance
        if farthest != -1 and farthest_distance > tolerance:
            keep[farthest] = True
            stack.append((first, farthest))
            stack.append((farthest, last))
    return [point for point, kept in zip(points, keep) if kept]


def rounded(points: list) -> list:
    """Points rounded to DECIMALS places, a point that rounds onto the one before it dropped.
    [(88.61661, 27.33333), (88.61649, 27.33349)] -> [[88.617, 27.333]]"""
    out = []
    for lon, lat in points:
        point = [round(lon, DECIMALS), round(lat, DECIMALS)]
        if not out or out[-1] != point:
            out.append(point)
    return out


def simple_ring(ring: list, tolerance: float) -> list | None:
    """A polygon's ring simplified and rounded, or None when it shrinks below a triangle (an islet smaller than the
    tolerance). A 200-point coastline ring -> perhaps 30 points, still closed; a 5-point islet 0.005 degrees across at
    tolerance 0.02 -> None."""
    points = rounded(douglas_peucker(ring, tolerance))
    if len(points) < 4:
        return None
    return points


def simple_polygons(shape: shapefile.Shape, tolerance: float) -> list:
    """A shape's polygons ([outer ring, holes...] each) simplified; rings that vanish are left out, and a polygon whose
    outer ring vanishes goes with its holes."""
    geometry = shape.__geo_interface__
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    out = []
    for polygon in polygons:
        outer = simple_ring(polygon[0], tolerance)
        if outer is None:
            continue
        rings = [outer]
        for hole in polygon[1:]:
            simplified = simple_ring(hole, tolerance)
            if simplified is not None:
                rings.append(simplified)
        out.append(rings)
    return out


def rings_of(shape: shapefile.Shape) -> list:
    """The full-detail rings of a shape, each a list of (lon, lat), closed (first point = last)."""
    rings = []
    starts = list(shape.parts) + [len(shape.points)]
    for start, end in zip(starts, starts[1:]):
        rings.append([tuple(point) for point in shape.points[start:end]])
    return rings


def edge_key(a: tuple, b: tuple) -> tuple:
    """The same key for an edge whichever way round it is walked. ((1, 2), (0, 5)) and ((0, 5), (1, 2)) ->
    ((0, 5), (1, 2))"""
    if a <= b:
        return (a, b)
    return (b, a)


def shared_borders(rings_by_owner: dict) -> list:
    """The lines two owners (countries, or states) share, each once, at full detail. An edge walked by two owners'
    rings is a border; a border line runs on while the same two owners share it, so it ends at every point where three
    meet and two lines never cross a junction a simplification could move. Coastlines (one owner) aren't borders.
    Two squares side by side sharing the edge (1, 0)-(1, 1) -> [[(1, 0), (1, 1)]] (in whichever direction it is
    first walked)."""
    owners_of = {}
    for owner, rings in rings_by_owner.items():
        for ring in rings:
            for a, b in zip(ring, ring[1:]):
                owners_of.setdefault(edge_key(a, b), set()).add(owner)
    lines = []
    done = set()
    for rings in rings_by_owner.values():
        for ring in rings:
            line = []
            line_owners = None
            for a, b in zip(ring, ring[1:]):
                key = edge_key(a, b)
                owners = owners_of[key]
                is_border = len(owners) >= 2 and key not in done
                carries_on = is_border and owners == line_owners and line and line[-1] == a
                if carries_on:
                    line.append(b)
                else:
                    if len(line) >= 2:
                        lines.append(line)
                    line = []
                    line_owners = None
                    if is_border:
                        line = [a, b]
                        line_owners = owners
                if is_border:
                    done.add(key)
            if len(line) >= 2:
                lines.append(line)
    return lines


def simple_lines(lines: list, tolerance: float) -> list:
    """Border lines simplified and rounded; a line that rounds to a single point is left out."""
    out = []
    for line in lines:
        points = rounded(douglas_peucker(line, tolerance))
        if len(points) >= 2:
            out.append(points)
    return out


def area_feature(properties: dict, polygons: list) -> dict:
    """One GeoJSON feature for a country or state: a MultiPolygon of its simplified polygons."""
    return {"type": "Feature", "properties": properties,
            "geometry": {"type": "MultiPolygon", "coordinates": polygons}}


def borders_feature(lines: list) -> dict:
    """The one feature holding all the border lines, marked `"borders": true`."""
    return {"type": "Feature", "properties": {"borders": True},
            "geometry": {"type": "MultiLineString", "coordinates": lines}}


def collection(features: list) -> dict:
    return {"type": "FeatureCollection", "features": features}


def land(reader: shapefile.Reader) -> dict:
    """The land, every polygon its own feature (so the map can skip those out of view)."""
    features = []
    for shape in reader.iterShapes():
        for polygon in simple_polygons(shape, LAND_TOLERANCE):
            features.append(area_feature({}, [polygon]))
    return collection(features)


def other_names(record: dict, name: str) -> list:
    """A country's other names Natural Earth knows, without repeats or its own name.
    United States: ADMIN "United States of America", NAME_LONG "United States" -> ["United States of America"]"""
    aliases = []
    for field in ("ADMIN", "NAME_LONG", "NAME_EN"):
        other = record[field]
        if other and other != name and other not in aliases:
            aliases.append(other)
    return aliases


def countries(reader: shapefile.Reader) -> dict:
    """Every country with its name, other names and label point, then the borders between them."""
    features = []
    rings_by_owner = {}
    for shape_record in reader.iterShapeRecords():
        record = shape_record.record.as_dict()
        name = record["NAME"]
        properties = {"name": name}
        aliases = other_names(record, name)
        if aliases:
            properties["aliases"] = aliases
        properties["label"] = [round(record["LABEL_X"], DECIMALS), round(record["LABEL_Y"], DECIMALS)]
        polygons = simple_polygons(shape_record.shape, COUNTRY_TOLERANCE)
        if polygons:  # a country smaller than the tolerance (Monaco, the Vatican) has no shape to fill
            features.append(area_feature(properties, polygons))
        rings_by_owner[record["ADM0_A3"]] = rings_of(shape_record.shape)
    features.append(borders_feature(simple_lines(shared_borders(rings_by_owner), BORDER_TOLERANCE)))
    return collection(features)


def indian_states(reader: shapefile.Reader) -> dict:
    """India's states and union territories with their names and label points, then the borders between them."""
    features = []
    rings_by_owner = {}
    for shape_record in reader.iterShapeRecords():
        record = shape_record.record.as_dict()
        if record["adm0_a3"] != "IND":
            continue
        name = record["name"]
        label = [round(record["longitude"], DECIMALS), round(record["latitude"], DECIMALS)]
        polygons = simple_polygons(shape_record.shape, STATE_TOLERANCE)
        if polygons:
            features.append(area_feature({"name": name, "label": label}, polygons))
        rings_by_owner[name] = rings_of(shape_record.shape)
    features.append(borders_feature(simple_lines(shared_borders(rings_by_owner), STATE_TOLERANCE)))
    return collection(features)


def places(reader: shapefile.Reader) -> dict:
    """Natural Earth's populated places: name -> [lat, lon, country], the biggest first when names repeat, so the
    plain name is the biggest place and the others are keyed "Name, Country" (Hyderabad is India's; Pakistan's is
    "Hyderabad, Pakistan"). An ASCII spelling that differs ("Sao Paulo") is added as a key of its own when free."""
    records = [record.as_dict() for record in reader.iterRecords(
        fields=["name", "nameascii", "adm0name", "latitude", "longitude", "pop_max"])]
    records.sort(key=lambda record: -record["pop_max"])
    out = {}
    for record in records:
        entry = [round(record["latitude"], DECIMALS), round(record["longitude"], DECIMALS), record["adm0name"]]
        name = record["name"]
        key = name
        if key in out:
            key = f"{name}, {record['adm0name']}"
        if key in out:
            continue  # a second place of the same name in the same country: the bigger one stands
        out[key] = entry
        ascii_name = record["nameascii"]
        if ascii_name and ascii_name != name and ascii_name not in out:
            out[ascii_name] = entry
    return out


def write(name: str, data: dict) -> int:
    """Writes one file to the kit's geo folder, as compact JSON; its size in bytes."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path = OUT / name
    path.write_text(text + "\n", encoding="utf-8")
    return path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the explainer-video kit's offline map data.")
    default_downloads = Path(tempfile.gettempdir()) / "natural-earth"
    parser.add_argument("--downloads", type=Path, default=default_downloads, help="where the zips are kept")
    args = parser.parse_args()
    args.downloads.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    built = {}
    versions = {}
    for file_name, path, build in (("land.json", LAND, land), ("countries.json", COUNTRIES, countries),
                                   ("states-in.json", STATES, indian_states), ("places.json", PLACES, places)):
        reader, version = read_zip(download(path, args.downloads))
        built[file_name] = write(file_name, build(reader))
        versions[file_name] = f"{Path(path).name} {version}"

    for file_name, size in built.items():
        print(f"{file_name:16} {size / 1000:8.1f} kB   from {versions[file_name]}")
    total = sum(built.values())
    print(f"{'total':16} {total / 1000:8.1f} kB   (limit {LIMIT / 1000:.0f} kB)")
    if total > LIMIT:
        raise SystemExit("over the limit: raise a tolerance")


if __name__ == "__main__":
    main()
