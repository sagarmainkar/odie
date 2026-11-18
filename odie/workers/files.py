"""A Worker's own files: write_file and read_file, bound to the job's folder. The chat's make_file lands in the
workspace root and makes only the kinds the chat can show; a Worker writes any text file (fib.py, a Makefile) in its
own folder, with no tap: the folder is the job's, and nothing outside it can be reached through these two.

These run in Odie's own process, outside the sandbox, while something the job started might still be swapping links in
its folder (security review, 19 Nov 2026). So a path is never resolved and then opened: every part of it is opened
one by one from the folder, refusing symlinks (O_NOFOLLOW) at every step, so a link planted anywhere along the way
fails the call instead of leading out."""
from __future__ import annotations

import os
from pathlib import Path

from google.adk.tools import FunctionTool

MAX_WRITE = 1_000_000
MAX_READ = 200_000


def inside(folder: Path, name: str) -> Path | None:
    """The path a name means inside the folder, or None when it would leave it (by its words; links are refused when
    it is opened). ("fib.py") -> <folder>/fib.py; ("src/a.py") -> <folder>/src/a.py; ("../x") -> None;
    ("/etc/hosts") -> None."""
    folder = folder.resolve()
    if Path(name).is_absolute():
        target = Path(os.path.normpath(name))
    else:
        target = Path(os.path.normpath(folder / name))
    if target == folder or folder not in target.parents:
        return None
    return target


def _parts(folder: Path, target: Path) -> list[str]:
    return list(target.relative_to(folder.resolve()).parts)


def open_inside(folder: Path, name: str, flags: int, make_dirs: bool = False, mode: int = 0o644) -> int:
    """A file descriptor for a path inside the folder, opened part by part from the folder with O_NOFOLLOW, so no
    symlink is ever followed. make_dirs: make missing folders on the way (writing). Raises OSError (ELOOP for a link,
    ENOENT for a missing part) or ValueError (a path that leaves the folder)."""
    target = inside(folder, name)
    if target is None:
        raise ValueError("outside the folder")
    parts = _parts(folder, target)
    nofollow_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(str(folder.resolve()), nofollow_dir)
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, nofollow_dir, dir_fd=fd)
            except FileNotFoundError:
                if not make_dirs:
                    raise
                os.mkdir(part, 0o755, dir_fd=fd)
                next_fd = os.open(part, nofollow_dir, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return os.open(parts[-1], flags | os.O_NOFOLLOW, mode, dir_fd=fd)
    finally:
        os.close(fd)


def make_job_file_tools(folder: Path) -> list[FunctionTool]:
    async def write_file(name: str, content: str) -> dict:
        """Write a text file in your folder, whole: name is the path inside your folder ("fib.py", "src/app.py"); content is the whole file. Use it for every file you make; the shell is for running things."""
        data = (content or "").encode("utf-8")
        if len(data) > MAX_WRITE:
            return {"error": "That's more than 1 MB: make it shorter, or split it into files."}
        try:
            fd = open_inside(folder, name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, make_dirs=True)
        except ValueError:
            return {"error": "Only paths inside your folder: a name like notes.md or src/app.py."}
        except OSError as e:
            return {"error": f"Can't write {name}: {e.strerror or e} (a link, or not a plain file)."}
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return {"written": str(inside(folder, name)), "bytes": len(data)}

    async def read_file(name: str) -> dict:
        """Read a text file in your folder: name is the path inside it. Long files are cut at 200,000 characters."""
        try:
            fd = open_inside(folder, name, os.O_RDONLY)
        except ValueError:
            return {"error": "Only paths inside your folder."}
        except FileNotFoundError:
            return {"error": f"There's no file at {name} in your folder."}
        except OSError as e:
            return {"error": f"Can't read {name}: {e.strerror or e} (a link, or not a plain file)."}
        with os.fdopen(fd, "rb") as f:
            raw = f.read(MAX_READ * 4 + 1)
        text = raw.decode(errors="replace")
        out = {"text": text[:MAX_READ]}
        if len(text) > MAX_READ:
            out["cut"] = True
        return out

    return [FunctionTool(write_file), FunctionTool(read_file)]
