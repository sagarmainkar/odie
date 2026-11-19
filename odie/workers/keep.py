"""Keep it (simpler Workers, 19 Nov 2026): a finished job's card offers "Keep it in <folder>" when the Worker said what
is worth keeping (report's keep: a path inside its folder) and the user named a folder of his in his request (code
found it: odie.workers.tools.keep_place). His tap in the app copies it there, by code, in Odie's own process, outside
every sandbox, so the copy itself is where the rules are:
  - the source is inside the job's folder, reached without any link and without "..", and not hidden (the job's own
    working folders, .home, .cache, are never kept);
  - the destination is checked again at the tap: still the real folder he named, still one of his own;
  - nothing is overwritten: <name>, else <name>-2, -3 … (claimed with an exclusive create, so never two at once);
  - a link inside the tree is copied as a link only when it is relative and stays inside the tree; any other link,
    and anything that isn't a file or a folder (a pipe, a socket), is left out and counted;
  - a git repository comes without what would run on its own once it is his: its hooks, its settings (core.fsmonitor,
    a pager, an alias…: replaced by a fresh settings file that keeps only its https address and branch), a worktree's
    settings, submodules' and worktrees' own git folders, a pointer to another repository's folder, borrowed objects.
    Everything else comes as the Worker left it, as a clone of his own would (its files are someone else's code);
  - nothing is run, nothing in the job's folder is changed or deleted, set-user-id and write-for-others bits are
    dropped, and nothing bigger than KEEP_MOST_BYTES is copied at all."""
from __future__ import annotations

import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

KEEP_MOST_BYTES = 2 * 1024 ** 3
KEEP_WORDS = "2 GB"  # KEEP_MOST_BYTES as the refusal says it
GIT_LEFT_OUT = ("hooks", "config", "config.worktree", "modules", "worktrees")  # in a .git: what could run on its own
SAFE_URL = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?/[A-Za-z0-9._~/-]+$")
SAFE_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
_keeping: set[str] = set()  # jobs whose copy is running now: a double tap copies once
_lock = threading.Lock()


class KeepRefused(Exception):
    """Why a keep didn't happen, in words for the card."""


class KeepStopped(KeepRefused):
    """The copy started and stopped part way (a full disk, a file that went): what was copied stays where it is, in
    path, never deleted from his folder; reason says why, in the system's words."""

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"the copy stopped part way ({reason}); the part already copied is in {path}")


@dataclass
class Kept:
    """Where a keep went and what it left out."""
    path: Path
    links_left_out: int = 0
    others_left_out: int = 0
    git_reset: bool = False
    venvs_left_out: list[str] = field(default_factory=list)  # Python environments, by their path inside the copy

    def line(self, home_form) -> str:
        """The card's line: "Kept in ~/code/demos/app" and, when anything was left out, what: "Kept in
        ~/code/demos/app; left out 3 links that point outside it; its git hooks and settings stayed behind; left out
        its Python environment .venv (make it again with python3 -m venv)"."""
        words = f"Kept in {home_form(str(self.path))}"
        if self.links_left_out == 1:
            words += "; left out 1 link that points outside it"
        elif self.links_left_out:
            words += f"; left out {self.links_left_out} links that point outside it"
        if self.others_left_out:
            words += f"; left out {self.others_left_out} special files"
        if self.git_reset:
            words += "; its git hooks and settings stayed behind"
        for venv in self.venvs_left_out:
            words += f"; left out its Python environment {venv} (make it again with python3 -m venv)"
        return words


def source_in(folder: Path, given: str) -> Path:
    """What to copy, as its real path, when it is inside the job's folder; else KeepRefused. Inside means: a path
    relative to the folder (or an absolute one inside it), no "..", no hidden part, no link anywhere along it, and it
    exists.
      "app" -> <folder>/app;  "<folder>/app/src" -> <folder>/app/src
      "../outside", "app/../../x", "/etc", "", ".", ".home", "app/.git" -> refused
      "app" when app is a link (to ~/.ssh, or anywhere) -> refused"""
    text = (given or "").strip()
    root = folder.resolve()
    path = Path(text)
    if not text or ".." in path.parts:
        raise KeepRefused("what to keep must be a path inside the job's folder")
    if path.is_absolute():
        rel = None
        for base in (folder, root):
            if path == base or base in path.parents:
                rel = path.relative_to(base)
        if rel is None:
            raise KeepRefused("what to keep must be inside the job's folder")
    else:
        rel = path
    if not rel.parts:
        raise KeepRefused("the job's whole folder is never kept: name what in it")
    if any(part.startswith(".") for part in rel.parts):
        raise KeepRefused("hidden files and the job's own working folders are never kept")
    step = root
    for part in rel.parts:
        step = step / part
        if step.is_symlink():
            raise KeepRefused("what to keep goes through a link")
    if not step.exists():
        raise KeepRefused("it isn't in the job's folder any more")
    real = step.resolve()
    if root not in real.parents:
        raise KeepRefused("what to keep must be inside the job's folder")
    return real


def relative_keep(folder: Path, given: str | None) -> str:
    """What a Worker's report says to keep, as a path relative to its folder, or "" when it isn't something source_in
    would copy: "app" -> "app"; "<folder>/app" -> "app"; "../../elsewhere" -> ""; None -> ""."""
    if not given:
        return ""
    try:
        real = source_in(folder, given)
    except KeepRefused:
        return ""
    return str(real.relative_to(folder.resolve()))


def size_of(source: Path, most: int) -> int:
    """The bytes of the files in source (links not followed), counting stops once past `most`."""
    if not source.is_dir():
        return source.lstat().st_size
    total = 0
    for here, dirs, files in os.walk(source, followlinks=False):
        for name in files:
            total += os.lstat(os.path.join(here, name)).st_size
            if total > most:
                return total
    return total


def claim(dest_dir: Path, name: str, is_dir: bool) -> Path:
    """A new name in dest_dir that nothing has, made at once (an exclusive create, so never an overwrite):
    "app" -> app, else app-2, app-3…;  "notes.txt" -> notes.txt, else notes-2.txt."""
    stem, suffix = name, ""
    if not is_dir:
        stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        candidate = dest_dir / name
        if n > 1:
            candidate = dest_dir / f"{stem}-{n}{suffix}"
        try:
            if is_dir:
                os.mkdir(candidate, 0o755)
            else:
                os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600))
            return candidate
        except FileExistsError:
            n += 1


def copy_file(src: Path, dst: Path, create: bool) -> None:
    """One regular file's bytes, links never followed at either end; its mode without set-id bits or write for
    others (an executable stays executable, as in a clone). create: dst is new; else dst was just claimed."""
    flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_TRUNC
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    src_fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        mode = os.fstat(src_fd).st_mode & 0o755
        dst_fd = os.open(dst, flags, 0o600)
        with os.fdopen(src_fd, "rb", closefd=False) as reading, os.fdopen(dst_fd, "wb") as writing:
            shutil.copyfileobj(reading, writing)
        os.chmod(dst, mode, follow_symlinks=False)
    finally:
        os.close(src_fd)


def link_stays_inside(link: Path, target: str, root: Path) -> bool:
    """Whether a link inside the tree may be copied as a link: only a relative one that ends inside the tree.
      "docs/a.md" from app/latest.md -> True;  "../.." -> False;  "/Users/me/.ssh" -> False;
      an absolute path back into the tree -> False (once copied it would point into the job's folder)"""
    if os.path.isabs(target):
        return False
    ends = (link.parent / target).resolve()
    return ends == root or root in ends.parents


def copy_tree(src_dir: Path, dst_dir: Path, root: Path, kept: Kept) -> None:
    """Every entry of src_dir into dst_dir (already made), by the rules in this module's notes."""
    for entry in sorted(os.scandir(src_dir), key=lambda e: e.name):
        src = Path(entry.path)
        dst = dst_dir / entry.name
        if entry.is_symlink():
            target = os.readlink(src)
            if link_stays_inside(src, target, root):
                os.symlink(target, dst)
            else:
                kept.links_left_out += 1
        elif entry.is_dir(follow_symlinks=False):
            if entry.name == ".git":
                copy_git(src, dst, root, kept)
            elif is_python_env(src):
                kept.venvs_left_out.append(str(src.relative_to(root)))
            else:
                os.mkdir(dst, 0o755)
                copy_tree(src, dst, root, kept)
        elif entry.is_file(follow_symlinks=False):
            if entry.name == ".git":
                kept.git_reset = True  # "gitdir: …": a pointer to another folder's settings and hooks
                continue
            copy_file(src, dst, create=True)
        else:
            kept.others_left_out += 1


def is_python_env(folder: Path) -> bool:
    """Whether a folder is a Python environment (a venv: it holds pyvenv.cfg). Its interpreter links and its scripts'
    first lines name the job's folder by absolute path, so a copy would run nothing: it is left out, and the line says
    to make it again. node_modules is not one: its links are relative and come along.
      app/.venv with pyvenv.cfg -> True;  app/node_modules -> False;  app/src -> False"""
    config = folder / "pyvenv.cfg"
    return config.is_file() and not config.is_symlink()


def copy_git(src: Path, dst: Path, root: Path, kept: Kept) -> None:
    """A .git folder without its hooks and settings (GIT_LEFT_OUT) or borrowed objects, and a fresh settings file."""
    kept.git_reset = True
    os.mkdir(dst, 0o755)
    for entry in sorted(os.scandir(src), key=lambda e: e.name):
        if entry.name in GIT_LEFT_OUT:
            continue
        one = Kept(dst)
        if entry.is_dir(follow_symlinks=False) and not entry.is_symlink():
            os.mkdir(dst / entry.name, 0o755)
            copy_tree(Path(entry.path), dst / entry.name, root, one)
        elif entry.is_file(follow_symlinks=False) and not entry.is_symlink():
            copy_file(Path(entry.path), dst / entry.name, create=True)
        elif entry.is_symlink():
            kept.links_left_out += 1
        else:
            kept.others_left_out += 1
        kept.links_left_out += one.links_left_out
        kept.others_left_out += one.others_left_out
    alternates = dst / "objects" / "info" / "alternates"
    if alternates.exists() or alternates.is_symlink():
        alternates.unlink()  # objects borrowed from a folder outside: never pointed at from his copy
    (dst / "config").write_text(fresh_git_config(src))


def fresh_git_config(git_dir: Path) -> str:
    """The settings a kept repository gets: the plain defaults, its origin when that is a plain https address, and
    its branch's link to it. Nothing else of the old file (a command in it would run on his next git status).
      old: [remote "origin"] url = https://github.com/example/app.git, HEAD on main
        -> core defaults + [remote "origin"] that url + [branch "main"] remote = origin
      old: url = ext::sh -c 'touch x', or no file -> core defaults only"""
    lines = ["[core]", "\trepositoryformatversion = 0", "\tfilemode = true", "\tbare = false",
             "\tlogallrefupdates = true"]
    old = read_small(git_dir / "config")
    found = re.search(r'\[remote "origin"\]([^\[]*)', old)
    url = ""
    if found:
        url_line = re.search(r"^\s*url\s*=\s*(\S+)\s*$", found.group(1), re.M)
        if url_line and SAFE_URL.match(url_line.group(1)):
            url = url_line.group(1)
    if url:
        lines += ['[remote "origin"]', f"\turl = {url}", "\tfetch = +refs/heads/*:refs/remotes/origin/*"]
        head = read_small(git_dir / "HEAD").strip()
        branch = head.removeprefix("ref: refs/heads/")
        if head.startswith("ref: refs/heads/") and SAFE_BRANCH.match(branch) and ".." not in branch:
            lines += [f'[branch "{branch}"]', "\tremote = origin", f"\tmerge = refs/heads/{branch}"]
    return "\n".join(lines) + "\n"


def read_small(path: Path) -> str:
    """A small plain file's text, never through a link; "" when it isn't one."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return ""
    with os.fdopen(fd, "rb") as f:
        return f.read(65536).decode(errors="replace")


def copy_into(source: Path, dest_dir: Path) -> Kept:
    """Copy source (from source_in) into dest_dir under a new name; KeepRefused when it is too big (nothing copied)."""
    size = size_of(source, KEEP_MOST_BYTES)
    if size > KEEP_MOST_BYTES:
        raise KeepRefused(f"it is more than the {KEEP_WORDS} a tap copies, so nothing was copied; it stays in {source}")
    is_dir = source.is_dir()
    target = claim(dest_dir, source.name, is_dir)
    kept = Kept(target)
    try:
        if is_dir:
            copy_tree(source, target, source, kept)
        else:
            copy_file(source, target, create=False)
    except OSError as e:
        raise KeepStopped(target, e.strerror or str(e)) from e  # what was copied stays: never a delete in his folder
    return kept


def offered(row: dict) -> bool:
    """Whether a job's card offers Keep it: it finished with its result ready, its Worker named something to keep, he
    named a folder for it, and it hasn't been kept yet (a copy that stopped part way counts as not kept).
      done, ready, keep "app", keep_to "~/code/demos", not kept -> True
      the same after a copy that stopped part way -> True (Keep it again: a new copy under a new name)
      no keep_to (he named no folder) -> False;  kept already -> False;  blocked or failed -> False"""
    from odie.workers import store as jobs
    if row["status"] != "done" or row["outcome"] != "ready":
        return False
    if not row.get("keep") or not row.get("keep_to"):
        return False
    kept = jobs.kept_of(row)
    return not kept or bool(kept.get("partial"))


def destination_now(keep_to: str) -> Path:
    """The folder he named, checked again at the tap: still a real folder, still that one (not swapped for a link),
    still one of his own (odie.workers.tools.not_his_own); else KeepRefused.
      "<home>/code/demos", as it was -> that folder
      it was removed, or is now a link to ~/.ssh -> refused
      "<home>/.ssh" (never named, but a row says so) -> refused"""
    from odie.workers.tools import not_his_own, true_path
    path = Path(keep_to)
    if not path.is_dir():
        raise KeepRefused(f"{keep_to} isn't a folder any more")
    real = true_path(path)
    if str(real) != keep_to:
        raise KeepRefused(f"{keep_to} changed since the job started (it is a link now)")
    why = not_his_own(real)
    if why:
        raise KeepRefused(f"{keep_to}: {why}")
    return real


def copying(job_id: str) -> bool:
    """Whether his Keep it tap is copying this job's result right now: then no retry starts (odie.workers.router)."""
    with _lock:
        return job_id in _keeping


def keep_job(row: dict) -> Kept:
    """His tap's work: the checks, then the copy. KeepRefused with the words when anything is off."""
    from odie.workers import store as jobs
    if row["status"] in jobs.GOING:
        raise KeepRefused("it's still going")
    if not offered(row):
        raise KeepRefused("there's nothing to keep here")
    with _lock:
        if row["id"] in _keeping:
            raise KeepRefused("it's being copied now")
        _keeping.add(row["id"])
    try:
        dest = destination_now(row["keep_to"])
        source = source_in(Path(row["folder"]), row["keep"])
        return copy_into(source, dest)
    finally:
        with _lock:
            _keeping.discard(row["id"])
