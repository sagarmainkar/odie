"""A Worker's own files: write_file and read_file, bound to the job's folder. The chat's make_file lands in the
workspace root and makes only the kinds the chat can show; a Worker writes any text file (fib.py, a Makefile) in its
own folder, with no tap: the folder is the job's, and nothing outside it can be reached through these two."""
from __future__ import annotations

from pathlib import Path

from google.adk.tools import FunctionTool

MAX_WRITE = 1_000_000
MAX_READ = 200_000


def inside(folder: Path, name: str) -> Path | None:
    """The path a name means inside the folder, or None when it would leave it.
    ("fib.py") -> <folder>/fib.py; ("src/a.py") -> <folder>/src/a.py; ("../x") -> None; ("/etc/hosts") -> None."""
    folder = folder.resolve()
    target = (folder / name).resolve() if not Path(name).is_absolute() else Path(name).resolve()
    if target == folder or folder not in target.parents:
        return None
    return target


def make_job_file_tools(folder: Path) -> list[FunctionTool]:
    async def write_file(name: str, content: str) -> dict:
        """Write a text file in your folder, whole: name is the path inside your folder ("fib.py", "src/app.py"); content is the whole file. Use it for every file you make; the shell is for running things."""
        target = inside(folder, name)
        if target is None:
            return {"error": "Only paths inside your folder: a name like notes.md or src/app.py."}
        data = (content or "").encode("utf-8")
        if len(data) > MAX_WRITE:
            return {"error": "That's more than 1 MB: make it shorter, or split it into files."}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"written": str(target), "bytes": len(data)}

    async def read_file(name: str) -> dict:
        """Read a text file in your folder: name is the path inside it. Long files are cut at 200,000 characters."""
        target = inside(folder, name)
        if target is None:
            return {"error": "Only paths inside your folder."}
        if not target.is_file():
            return {"error": f"There's no file at {name} in your folder."}
        text = target.read_text(errors="replace")
        cut = len(text) > MAX_READ
        return {"text": text[:MAX_READ], **({"cut": True} if cut else {})}

    return [FunctionTool(write_file), FunctionTool(read_file)]
