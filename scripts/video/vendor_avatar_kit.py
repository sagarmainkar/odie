"""Makes the two 3D-character libraries of the explainer-video kit (odie/video/kit/) from their npm packages.

Odie's three.js is the UMD build (global `THREE`, no loaders), and a video page is sealed: no network, no workers, no
`import`. So both libraries are turned into plain scripts that read the page's global `THREE`:

- gltf-loader.js: three r158's GLTFLoader (examples/jsm/loaders/GLTFLoader.js), with `toTrianglesDrawMode` copied in
  from BufferGeometryUtils.js. It sets `THREE.GLTFLoader`.
- three-vrm.min.js: @pixiv/three-vrm 3.5.5 (lib/three-vrm.module.min.js). It sets `window.THREE_VRM`.
- three-vrm.LICENSE: the package's LICENSE, copied as it is.

Run it once, with both npm tarballs unpacked by hand, each into its own empty folder (this script only reads text
from them and never runs anything in them):

    python scripts/video/vendor_avatar_kit.py <three@0.158.0 folder> <@pixiv/three-vrm@3.5.5 folder>

The folder may be the unpacked tarball (with its `package/` inside) or that `package/` folder itself. For three, a
folder that holds GLTFLoader.js and BufferGeometryUtils.js side by side is also fine. Both are
https://registry.npmjs.org/<name>/-/<file>.tgz; check the tarball against the registry's `dist.integrity` first.
Only the three output files are committed. If a library's file is shaped differently from what is expected here, the
script stops with a message instead of writing a file that would fail in the page."""
import re
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent.parent / "odie" / "video" / "kit"

LOADER_HEADER = (
    "// GLTFLoader from three.js r158 (npm three@0.158.0, examples/jsm/loaders/GLTFLoader.js), MIT, see "
    "three.LICENSE; turned into a plain script on the global THREE by scripts/video/vendor_avatar_kit.py.\n"
)
VRM_NOTE = (
    "// @pixiv/three-vrm 3.5.5, MIT (three-vrm.LICENSE); made a plain script on the global THREE by "
    "scripts/video/vendor_avatar_kit.py.\n"
)
# The three draw-mode constants that toTrianglesDrawMode (copied in from BufferGeometryUtils.js) reads from three.
DRAW_MODES = ["TriangleFanDrawMode", "TriangleStripDrawMode", "TrianglesDrawMode"]

# What may still be in a finished file: no `import ...`, no `export ...`, no `from "three"`.
LEFTOVER_IMPORT = re.compile(r"(^|[;}\s])import\s*[\w*{]")
LEFTOVER_EXPORT = re.compile(r"(^|[;}\s])export\s*[{d]")
LEFTOVER_FROM = re.compile(r"from\s*[\"']three[\"']")


def folder_with(root: Path, *relative_paths: str) -> Path:
    """The folder under `root` where all of `relative_paths` exist: `root` itself, else `root/package`.

    `folder_with(Path("three-vrm-3.5.5"), "lib/three-vrm.module.min.js")` -> `three-vrm-3.5.5/package` when the
    tarball was unpacked as it came; `three-0.158.0` when the file is directly inside it."""
    for folder in (root, root / "package"):
        if all((folder / relative).is_file() for relative in relative_paths):
            return folder
    sys.exit(f"{root}: expected {', '.join(relative_paths)} in it (or in its package/ folder)")


def find_file(root: Path, *candidates: str) -> Path:
    """The first of `candidates` (paths below `root` or `root/package`) that is a file.

    `find_file(three_dir, "GLTFLoader.js", "examples/jsm/loaders/GLTFLoader.js")` -> the flat layout's file when
    the folder has GLTFLoader.js in it, the npm layout's file when it has examples/jsm/loaders/GLTFLoader.js."""
    for folder in (root, root / "package"):
        for candidate in candidates:
            if (folder / candidate).is_file():
                return folder / candidate
    sys.exit(f"{root}: none of {', '.join(candidates)} found")


def check_plain_script(text: str, name: str) -> None:
    """Stops the script when `text` still has a module `import`, `export` or `from "three"` in it.

    `const X=THREE;` -> passes; `import*as X from"three";` or `export{a as B};` left in -> exits naming `name`."""
    problems = []
    if LEFTOVER_IMPORT.search(text):
        problems.append("an import")
    if LEFTOVER_EXPORT.search(text):
        problems.append("an export")
    if LEFTOVER_FROM.search(text):
        problems.append('a `from "three"`')
    if problems:
        sys.exit(f"{name} still has {' and '.join(problems)} after the conversion: the library's shape changed")


def make_gltf_loader(loader: str, utils: str) -> str:
    """GLTFLoader.js (an ES module) as a plain script that sets `THREE.GLTFLoader`.

    Takes the names the module imports from three and reads them from the global THREE instead, puts
    `toTrianglesDrawMode` (the one thing it imports from BufferGeometryUtils.js) in its place, and replaces
    `export { GLTFLoader };` with `THREE.GLTFLoader = GLTFLoader;`."""
    imports_from_three = re.search(r"^import \{(.*?)\} from 'three';\n", loader, re.DOTALL | re.MULTILINE)
    if imports_from_three is None:
        sys.exit("GLTFLoader.js: no `import { ... } from 'three';` found")
    names = [name.strip() for name in imports_from_three.group(1).split(",") if name.strip()]
    names = sorted(set(names + DRAW_MODES))

    helper_import = "import { toTrianglesDrawMode } from '../utils/BufferGeometryUtils.js';\n"
    if helper_import not in loader:
        sys.exit("GLTFLoader.js: its toTrianglesDrawMode import is not where it was in r158")
    export_line = "export { GLTFLoader };"
    if export_line not in loader:
        sys.exit("GLTFLoader.js: `export { GLTFLoader };` not found")
    helper_start = utils.find("function toTrianglesDrawMode(")
    if helper_start < 0:
        sys.exit("BufferGeometryUtils.js: toTrianglesDrawMode not found")
    helper_end = utils.index("\n}\n", helper_start) + 3
    helper = utils[helper_start:helper_end]

    body = loader[loader.index(helper_import) + len(helper_import):]
    body = body.replace(export_line, "")

    script = (
        LOADER_HEADER
        + "(function () {\n"
        + "const { " + ", ".join(names) + " } = THREE;\n"
        + helper + "\n"
        + body + "\n"
        + "THREE.GLTFLoader = GLTFLoader;\n"
        + "})();\n"
    )
    check_plain_script(script, "gltf-loader.js")
    return script


def make_three_vrm(module: str) -> str:
    """three-vrm.module.min.js (an ES module) as a plain script that sets `window.THREE_VRM`.

    - `import*as Cn from"three";` -> `const Cn=THREE;`
    - `import{BufferAttribute as Vt}from"three";` -> `const{BufferAttribute:Vt}=THREE;`
    - `export{$r as MToonMaterial,be as VRM};` -> `window.THREE_VRM={MToonMaterial:$r,VRM:be};`
    The first line (pixiv's licence header) stays first, then our note, then the code in a function of its own."""
    header, rest = module.split("\n", 1)
    if not header.startswith("/*!") or "pixiv" not in header:
        sys.exit("three-vrm.module.min.js: its first line is no longer pixiv's licence header")

    rest = re.sub(r'import\*as ([\w$]+) from"three";', r"const \1=THREE;", rest)
    rest = re.sub(r'import\{([^}]*)\}from"three";', named_import_as_const, rest)
    rest = re.sub(r"export\{([^}]*)\};", exports_as_assignment, rest)

    script = header + "\n" + VRM_NOTE + "(function(){" + rest.rstrip("\n") + "\n})();\n"
    check_plain_script(script, "three-vrm.min.js")
    if "window.THREE_VRM={" not in script:
        sys.exit("three-vrm.module.min.js: no `export{...};` found")
    return script


def named_import_as_const(match: re.Match) -> str:
    """`import{A as B,C}from"three";` (as the match) -> `const{A:B,C}=THREE;`."""
    pairs = [pair.strip().replace(" as ", ":") for pair in match.group(1).split(",") if pair.strip()]
    return "const{" + ",".join(pairs) + "}=THREE;"


def exports_as_assignment(match: re.Match) -> str:
    """`export{a as B,c as D};` (as the match) -> `window.THREE_VRM={B:a,D:c};`."""
    pairs = []
    for item in match.group(1).split(","):
        local, _, exported = item.strip().partition(" as ")
        if not exported:
            exported = local
        pairs.append(f"{exported}:{local}")
    return "window.THREE_VRM={" + ",".join(pairs) + "};"


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    three_root = Path(sys.argv[1])
    vrm_root = Path(sys.argv[2])

    loader_path = find_file(three_root, "GLTFLoader.js", "examples/jsm/loaders/GLTFLoader.js")
    utils_path = find_file(three_root, "BufferGeometryUtils.js", "examples/jsm/utils/BufferGeometryUtils.js")
    vrm_folder = folder_with(vrm_root, "lib/three-vrm.module.min.js", "LICENSE")

    gltf_loader = make_gltf_loader(loader_path.read_text(), utils_path.read_text())
    (KIT / "gltf-loader.js").write_text(gltf_loader)
    three_vrm = make_three_vrm((vrm_folder / "lib" / "three-vrm.module.min.js").read_text())
    (KIT / "three-vrm.min.js").write_text(three_vrm)
    shutil.copyfile(vrm_folder / "LICENSE", KIT / "three-vrm.LICENSE")

    print(f"wrote gltf-loader.js ({len(gltf_loader)} chars), three-vrm.min.js ({len(three_vrm)} chars), three-vrm.LICENSE")


if __name__ == "__main__":
    main()
