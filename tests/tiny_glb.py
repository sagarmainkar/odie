"""A tiny glTF 2.0 binary (.glb), made in code so no real 3D model is ever committed: one triangle with one face shape
(a morph target that moves its top corner 0.1 up), on one node named "Head", in one scene. About 700 bytes."""
import json
import struct

GLB_MAGIC = 0x46546C67  # "glTF"
JSON_CHUNK = 0x4E4F534A  # "JSON"
BIN_CHUNK = 0x004E4942   # "BIN\0"
FLOAT = 5126             # the glTF code for a 32-bit float component


def padded(data: bytes, filler: bytes) -> bytes:
    """`data` made a multiple of 4 bytes long with `filler`, as every glb chunk must be: 6 bytes -> 8."""
    missing = -len(data) % 4
    return data + filler * missing


def floats(values: list[float]) -> bytes:
    """Little-endian 32-bit floats, as glTF stores them."""
    return struct.pack(f"<{len(values)}f", *values)


def tiny_glb(morph: str = "aa", head: bool = True) -> bytes:
    """The glb: a triangle (0,0,0), (1,0,0), (0,1,0) whose face shape `morph` lifts the top corner by 0.1, its weight
    at rest 0. The node is named "Head" when `head`, else "Body" (a model without a head bone)."""
    positions = floats([0, 0, 0, 1, 0, 0, 0, 1, 0])
    offsets = floats([0, 0, 0, 0, 0, 0, 0, 0.1, 0])
    binary = positions + offsets
    node_name = "Head" if head else "Body"
    document = {
        "asset": {"version": "2.0", "generator": "odie tests"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": node_name, "mesh": 0}],
        "meshes": [{
            "primitives": [{"attributes": {"POSITION": 0}, "targets": [{"POSITION": 1}]}],
            "weights": [0],
            "extras": {"targetNames": [morph]},
        }],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(offsets)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": FLOAT, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]},
            {"bufferView": 1, "componentType": FLOAT, "count": 3, "type": "VEC3", "min": [0, 0, 0],
             "max": [0, 0.1, 0]},
        ],
    }
    json_chunk = padded(json.dumps(document).encode("utf-8"), b" ")
    bin_chunk = padded(binary, b"\0")
    chunks = (struct.pack("<II", len(json_chunk), JSON_CHUNK) + json_chunk
              + struct.pack("<II", len(bin_chunk), BIN_CHUNK) + bin_chunk)
    header = struct.pack("<III", GLB_MAGIC, 2, 12 + len(chunks))
    return header + chunks
