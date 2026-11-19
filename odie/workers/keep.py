"""Keep it (simpler Workers, 19 Nov 2026): a finished job's card offers "Keep it in <folder>" when the Worker said what
is worth keeping (report's keep: a path inside its folder) and the user named a folder of his in his request (code
found it: odie.workers.tools.keep_place). His tap in the app copies it there, by code, in Odie's own process, outside
every sandbox, so the copy itself is where the rules are:
  - the source is inside the job's folder, reached without any link and without "..", and not hidden (the job's own
    working folders, .home, .cache, are never kept);
  - the destination is checked again at the tap: still the real folder he named, still one of his own;
  - nothing is overwritten: <name>, else <name>-2, -3 … (claimed with an exclusive create, so never two at once);
    a single file goes into a new folder named after the job, never straight into his folder;
  - a link inside the tree is copied as a link only when it is relative and stays inside the tree; any other link,
    and anything that isn't a file or a folder (a pipe, a socket), is left out and counted;
  - a git folder (named .git in any case, or any folder git would take as one: HEAD, objects and refs) keeps only
    what makes it a repository (GIT_KEPT, compared casefolded: the Mac's disk ignores case, so .GIT and Hooks are
    git's own), with a fresh settings file written by code (its https address and branch only); hooks, every settings
    file, commondir and gitdir pointers, submodules' and worktrees' git folders, borrowed objects and anything unknown
    stay behind and are counted (independent review, 19 Nov 2026: an install script could plant them, and his next
    git status would have run them). A .gitattributes filter, diff or merge driver needs a settings entry the fresh
    file doesn't have, so it runs nothing. Everything else comes as the Worker left it, as a clone of his own would:
    files that run only when he runs them (a Makefile, an .envrc direnv must be told to allow) are his to decide;
  - a Python environment is left out (its paths point into the job's folder) and the line says to make it again;
  - nothing is run, nothing in the job's folder is changed or deleted, set-user-id and write-for-others bits are
    dropped, a pipe or device is never read, and nothing bigger than KEEP_MOST_BYTES is copied at all."""
from __future__ import annotations

import os
import re
import shutil
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path

KEEP_MOST_BYTES = 2 * 1024 ** 3
KEEP_WORDS = "2 GB"  # KEEP_MOST_BYTES as the refusal says it
# What a kept git folder keeps, compared casefolded (the Mac's disk ignores case: .GIT and Hooks are .git and hooks to
# git): only what makes it a repository with its history. Everything else stays behind and is counted: hooks, every
# settings file (config, config.worktree: a fresh config is written by code), commondir and gitdir (pointers to another
# folder's settings), modules and worktrees (other repositories' own git folders), anything unknown.
GIT_KEPT = frozenset({"head", "objects", "refs", "packed-refs", "shallow", "index", "description", "logs", "info"})
GIT_INFO_KEPT = frozenset({"exclude"})  # info/attributes and the rest stay behind
GIT_OBJECTS_LEFT_OUT = frozenset({"info/alternates", "info/http-alternates"})  # objects borrowed from elsewhere
SAFE_URL = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?/[A-Za-z0-9._~/-]+$")
SAFE_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
_keeping: set[str] = set()  # jobs whose copy is running now: a double tap copies once
# Held while a keep checks the job and while it records where it went, and while a retry starts (odie.workers.router):
# a keep never copies a job that is running again, a retry never starts under a copy, a second tap finds the first's
# record. Reentrant, so a check made under it may ask copying() again. Never held during the copy itself.
lock = threading.RLock()


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
    git_left_out: int = 0  # parts of its git folders that stayed behind (hooks, settings, pointers, unknown)
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
            words += "; its git settings were made fresh"
        if self.git_left_out == 1:
            words += "; 1 git part that could run commands (hooks, settings, pointers) stayed behind"
        elif self.git_left_out:
            words += f"; {self.git_left_out} git parts that could run commands (hooks, settings, pointers) stayed behind"
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


def claim(dest_dir: Path, name: str) -> Path:
    """A new folder in dest_dir that nothing has, made at once (an exclusive create, so never an overwrite):
    "app" -> app, else app-2, app-3…"""
    n = 1
    while True:
        candidate = dest_dir / name
        if n > 1:
            candidate = dest_dir / f"{name}-{n}"
        try:
            os.mkdir(candidate, 0o755)
            return candidate
        except FileExistsError:
            n += 1


class NotAFile(OSError):
    """What was to be copied as a file is a pipe, a device or a socket (found once it was open): never read from."""


def copy_file(src: Path, dst: Path, create: bool) -> None:
    """One regular file's bytes, links never followed at either end; its mode without set-id bits or write for
    others (an executable stays executable, as in a clone). create: dst is new; else dst was just claimed. Opened
    without waiting (a pipe would block a plain open) and checked once open: anything but a regular file raises
    NotAFile before dst is made."""
    flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_TRUNC
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    src_fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(src_fd)
        if not stat.S_ISREG(info.st_mode):
            raise NotAFile(f"{src.name} is not a file")
        mode = info.st_mode & 0o755
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


def is_git_name(name: str) -> bool:
    """Whether a name is git's own folder or pointer, as the Mac's disk sees it: ".git", ".GIT", ".Git" -> True;
    "git", ".gitignore", ".github" -> False."""
    return name.casefold() == ".git"


def looks_like_git_dir(folder: Path) -> bool:
    """Whether a folder not named .git is a git folder all the same (git takes one with HEAD, objects and refs, in any
    case, as a repository when he enters it): such a folder gets the same allow-list as a .git.
      app/docs holding HEAD, objects/, refs/ (a bare repository) -> True;  app/src -> False"""
    names = {}
    for entry in os.scandir(folder):
        names[entry.name.casefold()] = entry
    head, objects, refs = names.get("head"), names.get("objects"), names.get("refs")
    if head is None or objects is None or refs is None:
        return False
    return head.is_file(follow_symlinks=False) and objects.is_dir(follow_symlinks=False) and refs.is_dir(follow_symlinks=False)


def copy_tree(src_dir: Path, dst_dir: Path, root: Path, kept: Kept, skip: frozenset = frozenset(), rel: str = "") -> None:
    """Every entry of src_dir into dst_dir (already made), by the rules in this module's notes. skip: paths below
    src_dir, casefolded and "/"-joined, that stay behind as git parts (a git folder's borrowed objects); rel: where
    src_dir sits below the folder skip is counted from."""
    for entry in sorted(os.scandir(src_dir), key=lambda e: e.name):
        src = Path(entry.path)
        dst = dst_dir / entry.name
        here = f"{rel}{entry.name}".casefold()
        if here in skip:
            kept.git_left_out += 1
        elif is_git_name(entry.name) and (entry.is_symlink() or not entry.is_dir(follow_symlinks=False)):
            kept.git_reset = True
            kept.git_left_out += 1  # a pointer ("gitdir: …") or a link: another folder's settings and hooks
        elif entry.is_symlink():
            target = os.readlink(src)
            if link_stays_inside(src, target, root):
                os.symlink(target, dst)
            else:
                kept.links_left_out += 1
        elif entry.is_dir(follow_symlinks=False):
            if is_git_name(entry.name):
                copy_git(src, dst, root, kept, bare=False)
            elif is_python_env(src):
                kept.venvs_left_out.append(str(src.relative_to(root)))
            elif looks_like_git_dir(src):
                copy_git(src, dst, root, kept, bare=True)
            else:
                os.mkdir(dst, 0o755)
                copy_tree(src, dst, root, kept, skip, f"{here}/")
        elif entry.is_file(follow_symlinks=False):
            try:
                copy_file(src, dst, create=True)
            except NotAFile:
                kept.others_left_out += 1  # it was swapped for a pipe or a device after the listing
        else:
            kept.others_left_out += 1


def is_python_env(folder: Path) -> bool:
    """Whether a folder is a Python environment (a venv: it holds pyvenv.cfg). Its interpreter links and its scripts'
    first lines name the job's folder by absolute path, so a copy would run nothing: it is left out, and the line says
    to make it again. node_modules is not one: its links are relative and come along.
      app/.venv with pyvenv.cfg -> True;  app/node_modules -> False;  app/src -> False"""
    config = folder / "pyvenv.cfg"
    return config.is_file() and not config.is_symlink()


def copy_git(src: Path, dst: Path, root: Path, kept: Kept, bare: bool) -> None:
    """A git folder by its allow-list (GIT_KEPT, GIT_INFO_KEPT, objects without GIT_OBJECTS_LEFT_OUT), names compared
    casefolded, links never followed, and a fresh settings file written here. Everything else is counted as left out.
    bare: a git folder that isn't a .git (it holds the repository itself), so its fresh settings say so."""
    kept.git_reset = True
    os.mkdir(dst, 0o755)
    for entry in sorted(os.scandir(src), key=lambda e: e.name):
        key = entry.name.casefold()
        here = Path(entry.path)
        if key not in GIT_KEPT or entry.is_symlink():
            kept.git_left_out += 1
        elif key == "info" and entry.is_dir(follow_symlinks=False):
            os.mkdir(dst / entry.name, 0o755)
            for inner in sorted(os.scandir(here), key=lambda e: e.name):
                plain = inner.is_file(follow_symlinks=False) and not inner.is_symlink()
                if inner.name.casefold() in GIT_INFO_KEPT and plain:
                    copy_file(Path(inner.path), dst / entry.name / inner.name, create=True)
                else:
                    kept.git_left_out += 1
        elif entry.is_dir(follow_symlinks=False):
            skip = frozenset()
            if key == "objects":
                skip = GIT_OBJECTS_LEFT_OUT
            os.mkdir(dst / entry.name, 0o755)
            copy_tree(here, dst / entry.name, root, kept, skip)
        elif entry.is_file(follow_symlinks=False):
            try:
                copy_file(here, dst / entry.name, create=True)
            except NotAFile:
                kept.git_left_out += 1
        else:
            kept.git_left_out += 1
    (dst / "config").write_text(fresh_git_config(src, bare))


def fresh_git_config(git_dir: Path, bare: bool = False) -> str:
    """The settings a kept repository gets: the plain defaults, its origin when that is a plain https address, and
    its branch's link to it. Nothing else of the old file (a command in it would run on his next git status).
      old: [remote "origin"] url = https://github.com/example/app.git, HEAD on main
        -> core defaults + [remote "origin"] that url + [branch "main"] remote = origin
      old: url = ext::sh -c 'touch x', or no file -> core defaults only"""
    bare_words = "false"
    if bare:
        bare_words = "true"
    lines = ["[core]", "\trepositoryformatversion = 0", "\tfilemode = true", f"\tbare = {bare_words}",
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


def copy_into(source: Path, dest_dir: Path, file_folder: str = "kept") -> Kept:
    """Copy source (from source_in) into dest_dir under a new name. A folder goes in as itself (app, else app-2…); a
    single file goes inside a new folder named file_folder (the job's name), never straight into his folder, where a
    CLAUDE.md or a conftest.py would act on every project beside it. KeepRefused when it is too big or is neither a
    file nor a folder (nothing copied); KeepStopped when the copy stops part way (what was copied stays).
      folder app -> <dest>/app;  file conftest.py, job "Try app" -> <dest>/try-app/conftest.py"""
    size = size_of(source, KEEP_MOST_BYTES)
    if size > KEEP_MOST_BYTES:
        raise KeepRefused(f"it is more than the {KEEP_WORDS} a tap copies, so nothing was copied; it stays in {source}")
    mode = source.lstat().st_mode
    is_dir = stat.S_ISDIR(mode)
    if not is_dir and not stat.S_ISREG(mode):
        raise KeepRefused("it is neither a file nor a folder (a pipe or a device), so nothing was copied")
    if is_dir:
        target = claim(dest_dir, source.name)
    else:
        target = claim(dest_dir, file_folder) / source.name
    kept = Kept(target)
    try:
        if is_dir:
            copy_tree(source, target, source, kept)
        else:
            copy_file(source, target, create=True)
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
    with lock:
        return job_id in _keeping


def record_of(kept: Kept) -> dict:
    """Where a keep went and what it left out, as the job's row keeps it (jobs.kept_json)."""
    from odie.store.db import now_iso
    return {"path": str(kept.path), "links_left_out": kept.links_left_out, "others_left_out": kept.others_left_out,
            "git_reset": kept.git_reset, "git_left_out": kept.git_left_out, "venvs_left_out": kept.venvs_left_out,
            "at": now_iso()}


def keep_job(store, job_id: str) -> Kept:
    """His tap's work: the checks on the job as it is now (read again under the lock), the copy, and the record of
    where it went, written before the lock lets a second tap or a retry look. KeepRefused with the words when anything
    is off; KeepStopped (recorded as partial) when the copy stopped part way."""
    from odie.store.db import now_iso
    from odie.workers import store as jobs
    from odie.workers.router import slug_of
    with lock:
        row = jobs.get(store, job_id)
        if row is None:
            raise KeepRefused("there's no such job")
        if row["status"] in jobs.GOING:
            raise KeepRefused("it's still going")
        if job_id in _keeping:
            raise KeepRefused("it's being copied now")
        if not offered(row):
            raise KeepRefused("there's nothing to keep here")
        _keeping.add(job_id)
    try:
        dest = destination_now(row["keep_to"])
        source = source_in(Path(row["folder"]), row["keep"])
        kept = copy_into(source, dest, slug_of(row["title"]))
    except KeepStopped as e:
        with lock:
            jobs.set_kept(store, job_id, {"path": str(e.path), "partial": True, "stopped": e.reason, "at": now_iso()})
            _keeping.discard(job_id)
        raise
    except BaseException:
        with lock:
            _keeping.discard(job_id)
        raise
    with lock:
        jobs.set_kept(store, job_id, record_of(kept))
        _keeping.discard(job_id)
    return kept
