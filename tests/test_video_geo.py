"""The map's shipped data: Jammu and Kashmir and Ladakh are drawn as India draws them (the whole India-view outline,
not the administered areas), checked straight on states-in.json."""
import json
from pathlib import Path

from odie.video import page

STATES = json.loads((Path(page.__file__).parent / "kit" / "geo" / "states-in.json").read_text())
SRINAGAR = (74.80, 34.08)  # (lon, lat), as the file stores points
MUZAFFARABAD = (73.47, 34.37)
GILGIT = (74.31, 35.92)
SIACHEN = (77.10, 35.40)
LEH = (77.58, 34.16)


def inside_ring(point: tuple, ring: list) -> bool:
    """Ray casting: whether a horizontal ray from the point crosses the ring an odd number of times."""
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def inside_state(point: tuple, name: str) -> bool:
    """Whether the point is in the named state: inside an outer ring and not in one of its holes (even-odd, as the
    kit fills)."""
    feature = next(f for f in STATES["features"] if f["properties"].get("name") == name)
    inside = False
    for polygon in feature["geometry"]["coordinates"]:
        for ring in polygon:
            if inside_ring(point, ring):
                inside = not inside
    return inside


def crosses(a: tuple, b: tuple, c: tuple, d: tuple) -> bool:
    """Whether segment a-b crosses segment c-d (each strictly to either side of the other)."""
    def turn(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    return turn(a, b, c) * turn(a, b, d) < 0 and turn(c, d, a) * turn(c, d, b) < 0


def state_borders() -> list:
    feature = next(f for f in STATES["features"] if f["properties"].get("borders"))
    return feature["geometry"]["coordinates"]


def test_gilgit_and_siachen_are_in_ladakh_and_muzaffarabad_in_jammu_and_kashmir():
    assert inside_state(GILGIT, "Ladakh")
    assert inside_state(SIACHEN, "Ladakh")
    assert inside_state(MUZAFFARABAD, "Jammu and Kashmir")
    assert inside_state(SRINAGAR, "Jammu and Kashmir") and inside_state(LEH, "Ladakh")
    assert not inside_state(GILGIT, "Jammu and Kashmir") and not inside_state(MUZAFFARABAD, "Ladakh")


def outline_of(name: str) -> list:
    """Every ring of a state, as s.region outlines it."""
    feature = next(f for f in STATES["features"] if f["properties"].get("name") == name)
    return [ring for polygon in feature["geometry"]["coordinates"] for ring in polygon]


def test_no_state_border_or_outline_runs_along_the_line_of_control_or_round_siachen():
    lines = state_borders() + outline_of("Jammu and Kashmir") + outline_of("Ladakh")
    for line in lines:
        for c, d in zip(line, line[1:]):
            assert not crosses(SRINAGAR, MUZAFFARABAD, c, d)
            assert not crosses(LEH, SIACHEN, c, d)
