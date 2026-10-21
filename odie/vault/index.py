"""Odie's index: one SQLite file (odie-index.db) with the vault's notes, their chunks, an FTS5 table over them (keyword
search, always on) and, when an embedding model is set, a normalised vector per chunk (meaning search; the two are merged
by reciprocal rank fusion). Every vector lives in the one vectors table, keyed by what it belongs to (kind "chunk" and
the chunk's id today; pictures join the same table), so one nearest-neighbour pass can search everything. Read-only on
the vault: it never writes a note, and never reads outside the vault folder."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from array import array
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from odie.memory.search import STOPWORDS
from odie.vault.chunks import parse

ALWAYS_IGNORED = (".obsidian", ".trash", ".git")
FILE = "odie-index.db"
OLD_FILE = "vault-index.db"  # the name before 2026-10-14, adopted on first use (adopt_old_index)
SCHEMA = """
create table if not exists notes (path text primary key, mtime real, size integer, sha1 text, title text,
                                  aliases text, tags text, links text);
create table if not exists chunks (id integer primary key, path text not null, ord integer, heading text, text text);
create index if not exists chunks_path on chunks(path);
create virtual table if not exists chunks_fts using fts5(heading, text, title, tokenize='unicode61 remove_diacritics 2');
create table if not exists vectors (kind text not null, ref text not null, vec blob not null, primary key (kind, ref));
create table if not exists meta (key text primary key, value text);
create table if not exists photos (uuid text primary key, kind text not null, taken text, people text, labels text, place text,
                                   city text, country text, albums text, extras text, favorite integer, screenshot integer,
                                   width integer, height integer, thumb text, big text);
create virtual table if not exists photos_fts using fts5(uuid unindexed, people, labels, place, albums, extras, taken,
                                                         tokenize='unicode61 remove_diacritics 2');
"""
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class AnyHit:
    """One result of search_all: a note passage or a picture, with the same score scale across kinds."""
    kind: str                 # "note", "photo" or "video"
    ref: str                  # the chunk id or the picture's uuid
    score: float
    note: Hit | None = None
    photo: PhotoHit | None = None


@dataclass(frozen=True)
class PhotoHit:
    uuid: str
    kind: str            # "photo" or "video"
    taken: str           # YYYY-MM-DD
    place: str
    people: list[str]
    labels: list[str]
    albums: list[str]
    extras: list[str]    # Apple's own notes worth a word: a holiday, a trip, a landmark, a pet, text seen in it
    has_thumb: bool      # a small copy is on this computer (the thumbnail route can serve it)
    score: float


@dataclass(frozen=True)
class Hit:
    path: str           # relative to the vault, e.g. "1-Projects/Trip.md"
    note: str           # its title
    heading: str
    text: str
    updated: str        # YYYY-MM-DD, from the file's modified time
    score: float
    id: int = 0         # the chunk's id in the index


def _day(mtime: float) -> str:
    return date.fromtimestamp(mtime).isoformat()


def index_path(data_dir: Path) -> Path:
    return Path(data_dir) / FILE


def adopt_old_index(data_dir: Path) -> None:
    """An install from before the one-index change keeps what it indexed: vault-index.db becomes odie-index.db. Its
    write-ahead log is folded in first, so rows that were only in the -wal file come along; the -wal and -shm files are
    gone after that. With odie-index.db already there (or no old file), nothing happens: an index is never overwritten.
      data/vault-index.db (+ -wal), no data/odie-index.db -> data/odie-index.db with every row, the old names gone
      data/odie-index.db already there                   -> untouched, vault-index.db left as it is"""
    data_dir = Path(data_dir)
    old, new = data_dir / OLD_FILE, data_dir / FILE
    if new.exists() or not old.is_file():
        return
    c = sqlite3.connect(old)
    try:
        c.execute("pragma wal_checkpoint(TRUNCATE)")
        c.execute("pragma journal_mode=DELETE")  # the -wal and -shm files are removed with the mode
    finally:
        c.close()
    old.rename(new)
    for side in ("-wal", "-shm"):
        (data_dir / (OLD_FILE + side)).unlink(missing_ok=True)


def _upgrade_vectors(c: sqlite3.Connection) -> None:
    """The vectors table before 2026-10-14 was keyed by chunk id alone; its rows become kind "chunk", ref "<id>"."""
    cols = [r[1] for r in c.execute("pragma table_info(vectors)")]
    if cols != ["chunk_id", "vec"]:
        return
    c.executescript("""
        create table vectors_new (kind text not null, ref text not null, vec blob not null, primary key (kind, ref));
        insert into vectors_new select 'chunk', cast(chunk_id as text), vec from vectors;
        drop table vectors;
        alter table vectors_new rename to vectors;
    """)


class VaultIndex:
    def __init__(self, db: Path, vault: Path | None, ignore: Iterable[str] = ()) -> None:
        """vault None: no notes folder (the index then holds photos alone; every notes call answers empty)."""
        self.db_path = Path(db)
        self.vault = Path(vault).expanduser().resolve() if vault else None
        self.ignore = tuple(i.strip("/") for i in ignore if i and i.strip("/"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as c:
            _upgrade_vectors(c)
            c.executescript(SCHEMA)

    def _db(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("pragma journal_mode=wal")
        return c

    # ── which files are notes ──
    def _inside(self, p: Path) -> bool:
        if self.vault is None:
            return False
        try:
            return p.resolve().is_relative_to(self.vault)
        except OSError:
            return False

    def _ignored(self, rel: Path) -> bool:
        if any(part in ALWAYS_IGNORED for part in rel.parts):
            return True
        text = rel.as_posix()
        return any(text == i or text.startswith(i + "/") for i in self.ignore)

    def files(self) -> list[Path]:
        """Every note: .md files under the vault, outside ignored folders, that really live inside the vault."""
        if self.vault is None or not self.vault.is_dir():
            return []
        out = []
        for p in sorted(self.vault.rglob("*.md")):
            rel = p.relative_to(self.vault)
            if p.is_file() and not self._ignored(rel) and self._inside(p):
                out.append(p)
        return out

    # ── indexing ──
    def _write(self, c: sqlite3.Connection, rel: str, text: str, st, sha1: str) -> None:
        parsed = parse(text, Path(rel).stem)
        self._forget(c, rel)
        c.execute("insert into notes values (?,?,?,?,?,?,?,?)",
                  (rel, st.st_mtime, st.st_size, sha1, parsed.title, json.dumps(parsed.aliases), json.dumps(parsed.tags),
                   json.dumps(parsed.links)))
        names = " | ".join([parsed.title, *parsed.aliases, " ".join(parsed.tags)])
        for i, ch in enumerate(parsed.chunks):
            cid = c.execute("insert into chunks(path, ord, heading, text) values (?,?,?,?)", (rel, i, ch.heading, ch.text)).lastrowid
            c.execute("insert into chunks_fts(rowid, heading, text, title) values (?,?,?,?)", (cid, ch.heading, ch.text, names))

    def _forget(self, c: sqlite3.Connection, rel: str) -> None:
        ids = [r["id"] for r in c.execute("select id from chunks where path=?", (rel,))]
        for cid in ids:
            c.execute("delete from chunks_fts where rowid=?", (cid,))
            if c.execute("delete from vectors where kind='chunk' and ref=?", (str(cid),)).rowcount:
                _bump(c)
        c.execute("delete from chunks where path=?", (rel,))
        c.execute("delete from notes where path=?", (rel,))

    def scan(self, progress: Callable[[int, int], None] | None = None) -> dict:
        """Bring the index up to date: new and changed notes read (by modified time and size, then content), notes that
        are gone removed."""
        files = self.files()
        seen, added, updated, unread = set(), 0, 0, []
        with self._db() as c:
            known = {r["path"]: r for r in c.execute("select path, mtime, size, sha1 from notes")}
            for i, p in enumerate(files):
                rel = p.relative_to(self.vault).as_posix()
                seen.add(rel)
                st = p.stat()
                row = known.get(rel)
                if row is None or row["mtime"] != st.st_mtime or row["size"] != st.st_size:
                    try:
                        text = p.read_text(errors="replace")
                    except OSError:  # no permission, or a cloud file not on this computer: kept as it was
                        unread.append(rel)
                        continue
                    sha1 = hashlib.sha1(text.encode()).hexdigest()
                    if row is not None and row["sha1"] == sha1:
                        c.execute("update notes set mtime=?, size=? where path=?", (st.st_mtime, st.st_size, rel))
                    else:
                        self._write(c, rel, text, st, sha1)
                        added, updated = (added + 1, updated) if row is None else (added, updated + 1)
                if progress:
                    progress(i + 1, len(files))
            gone = [rel for rel in known if rel not in seen]
            for rel in gone:
                self._forget(c, rel)
            c.execute("insert or replace into meta values ('scanned_at', ?)", (time.strftime("%Y-%m-%dT%H:%M:%S"),))
            more = f" and {len(unread) - 5} more" if len(unread) > 5 else ""
            self._set(c, "scan_warning", f"Couldn't read: {', '.join(unread[:5])}{more}" if unread else None)
        return {"added": added, "updated": updated, "removed": len(gone), "notes": len(files)}

    def index_file(self, path: Path) -> bool:
        """Read one note now (Odie just wrote it). False when it isn't a note of this vault."""
        p = Path(path)
        if not p.suffix == ".md" or not self._inside(p) or not p.is_file():
            return False
        rel = p.resolve().relative_to(self.vault)
        if self._ignored(rel):
            return False
        text = p.read_text(errors="replace")
        with self._db() as c:
            self._write(c, rel.as_posix(), text, p.stat(), hashlib.sha1(text.encode()).hexdigest())
        return True

    # ── searching ──
    def _hits(self, c: sqlite3.Connection, rows) -> list[Hit]:
        notes = {r["path"]: r for r in c.execute("select path, title, mtime from notes")}
        return [Hit(r["path"], notes[r["path"]]["title"], r["heading"], r["text"], _day(notes[r["path"]]["mtime"]), r["score"],
                    r["id"]) for r in rows if r["path"] in notes]

    def _keep(self, c: sqlite3.Connection, folder: str | None, since: str | None, tags: list[str] | None) -> Callable[[str], bool]:
        if not (folder or since or tags):
            return lambda path: True
        meta = {r["path"]: r for r in c.execute("select path, mtime, tags from notes")}
        folder = (folder or "").strip("/")
        wanted = {t.lstrip("#").lower() for t in tags or []}

        def keep(path: str) -> bool:
            n = meta.get(path)
            if n is None or (folder and not (path == folder or path.startswith(folder + "/"))):
                return False
            if since and _day(n["mtime"]) < since[:10]:
                return False
            return not wanted or bool(wanted & set(json.loads(n["tags"] or "[]")))
        return keep

    def keyword(self, query: str, k: int = 8, folder: str | None = None, since: str | None = None,
                tags: list[str] | None = None) -> list[Hit]:
        words = [w.lower() for w in _WORD.findall(query or "") if w.lower() not in STOPWORDS]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' + ("*" if len(w) >= 4 else "") for w in dict.fromkeys(words))
        with self._db() as c:
            keep = self._keep(c, folder, since, tags)
            limit = -1 if (folder or since or tags) else max(k * 6, 50)  # filtered: every match, so none is cut before it
            rows = c.execute("select c.id, c.path, c.heading, c.text, -bm25(chunks_fts) as score from chunks_fts "
                             "join chunks c on c.id = chunks_fts.rowid where chunks_fts match ? order by bm25(chunks_fts) "
                             "limit ?", (match, limit)).fetchall()
            hits = self._hits(c, [r for r in rows if keep(r["path"])])
        return hits[:k]

    # ── reading ──
    def resolve(self, note: str) -> Path | None:
        """A note by its path (with or without .md), file name, title or alias. None outside the vault or unknown."""
        name = (note or "").strip()
        if not name or self.vault is None:
            return None
        for cand in (name, name + ".md"):
            p = self.vault / cand
            if p.suffix == ".md" and p.is_file() and self._inside(p) and not p.is_symlink():
                rel = p.resolve().relative_to(self.vault)
                if not self._ignored(rel):
                    return p.resolve()
        low = name.lower().removesuffix(".md")
        with self._db() as c:
            rows = c.execute("select path, title, aliases from notes order by path").fetchall()
        for r in rows:
            stem = Path(r["path"]).stem.lower()
            names = {stem, r["path"].lower().removesuffix(".md"), (r["title"] or "").lower(),
                     *(a.lower() for a in json.loads(r["aliases"] or "[]"))}
            if low in names:
                p = self.vault / r["path"]
                return p.resolve() if p.is_file() and self._inside(p) else None
        return None

    def read(self, note: str, limit: int = 12000) -> str | None:
        p = self.resolve(note)
        if p is None:
            return None
        text = p.read_text(errors="replace")
        return text if len(text) <= limit else text[:limit] + "…"

    def linked(self, note: str) -> dict:
        """The notes this one links to, the ones linking to it, and the ones sharing a tag with it."""
        p = self.resolve(note)
        empty = {"links": [], "backlinks": [], "shared_tags": []}
        if p is None:
            return empty
        rel = p.relative_to(self.vault).as_posix()
        with self._db() as c:
            rows = {r["path"]: r for r in c.execute("select path, title, aliases, tags, links from notes")}
        me = rows.get(rel)
        if me is None:
            return empty
        links = []
        for target in json.loads(me["links"] or "[]"):
            hit = self.resolve(target)
            if hit is not None:
                links.append(hit.relative_to(self.vault).as_posix())
        names = {Path(rel).stem.lower(), rel.lower().removesuffix(".md"), (me["title"] or "").lower(),
                 *(a.lower() for a in json.loads(me["aliases"] or "[]"))}
        mine = set(json.loads(me["tags"] or "[]"))
        backlinks = [path for path, r in rows.items() if path != rel and names & {t.lower() for t in json.loads(r["links"] or "[]")}]
        shared = [path for path, r in rows.items() if path != rel and mine & set(json.loads(r["tags"] or "[]"))]
        return {"links": links, "backlinks": sorted(backlinks), "shared_tags": sorted(shared)}

    # ── meaning ──
    def _meta(self, c: sqlite3.Connection) -> dict[str, str]:
        return {r["key"]: r["value"] for r in c.execute("select key, value from meta")}

    def _set(self, c: sqlite3.Connection, key: str, value: str | None) -> None:
        if value is None:
            c.execute("delete from meta where key=?", (key,))
        else:
            c.execute("insert or replace into meta values (?,?)", (key, value))

    async def embed_pending(self, embedder, batch: int = 32, progress: Callable[[int, int], None] | None = None) -> int:
        """Embed the chunks that have no vector yet. Another model (name or vector size) clears the old vectors first.
        A failing embedder stops the run and is recorded for index_status; the next run tries again."""
        with self._db() as c:
            if self._meta(c).get("model") != embedder.name:
                c.execute("delete from vectors")
                _bump(c)
                self._set(c, "model", embedder.name)
                self._set(c, "dims", None)
            pending = c.execute("select c.id, c.heading, c.text, n.title from chunks c join notes n on n.path = c.path "
                                "where cast(c.id as text) not in (select ref from vectors where kind='chunk') order by c.id").fetchall()
        done = 0
        for i in range(0, len(pending), batch):
            rows = pending[i:i + batch]
            texts = [{"title": r["title"], "text": f"{r['heading']}\n{r['text']}"[:8000]} for r in rows]
            try:
                vecs = await embedder.embed(texts)
            except Exception as e:  # noqa: BLE001
                with self._db() as c:
                    self._set(c, "embed_error", f"{type(e).__name__}: {e}"[:300])
                return done
            done += self._store_vectors("chunk", [str(r["id"]) for r in rows], vecs)
            if progress:
                progress(min(i + batch, len(pending)), len(pending))
        with self._db() as c:
            self._set(c, "embed_error", None)
        return done

    def _store_vectors(self, kind: str, refs: list[str], vecs: list[list[float]]) -> int:
        """Keep these vectors; a vector of another size than the index's clears everything and starts the size over."""
        with self._db() as c:
            dims = self._meta(c).get("dims")
            for ref, v in zip(refs, vecs):
                if dims and int(dims) != len(v):  # same name, other size: start again with this one
                    c.execute("delete from vectors")
                    dims = None
                if not dims:
                    self._set(c, "dims", str(len(v)))
                    dims = str(len(v))
                c.execute("insert or replace into vectors values (?, ?, ?)", (kind, ref, _pack(v)))
            _bump(c)
        return len(refs)

    async def embed_pending_pictures(self, embedder, batch: int = 8, progress: Callable[[int, int], None] | None = None) -> int:
        """One vector per picture that has none yet: its words (people, what Photos saw, place, albums, date) and the
        best copy on this Mac together; the words alone when there's no copy. Only an embedder that sees pictures
        (Odie's own service) is asked; a failure is recorded like a notes one and the next run tries again."""
        if not getattr(embedder, "sees_pictures", False):
            return 0
        with self._db() as c:
            if self._meta(c).get("model") != embedder.name:
                return 0  # the notes pass sets the model first; a change of model clears every vector there
            pending = c.execute("select * from photos where uuid not in (select ref from vectors where kind='photo') "
                                "order by taken desc").fetchall()
        done = 0
        for i in range(0, len(pending), batch):
            rows = pending[i:i + batch]
            items = [(picture_words(r), picture_file(r)) for r in rows]
            try:
                vecs = await embedder.embed_pictures(items)
            except Exception as e:  # noqa: BLE001
                with self._db() as c:
                    self._set(c, "embed_error", f"pictures: {type(e).__name__}: {e}"[:300])
                return done
            done += self._store_vectors("photo", [r["uuid"] for r in rows], vecs)
            if progress:
                progress(min(i + batch, len(pending)), len(pending))
        with self._db() as c:
            self._set(c, "embed_error", None)
        return done

    def _vectors(self) -> tuple[list[int], list[list[float]]]:
        """Every chunk's vector, cached until the vectors change."""
        ids, vecs = self._vectors_of("chunk")
        return [int(i) for i in ids], vecs

    def _vectors_of(self, kind: str) -> tuple[list[str], list[list[float]]]:
        """Every vector of one kind ("chunk" or "photo"), cached until the vectors change."""
        cache = getattr(self, "_caches", None)
        if cache is None:
            cache = self._caches = {}
        with self._db() as c:
            key = (self._meta(c).get("vectors_version"), c.execute("select count(*) from vectors").fetchone()[0])
            if kind in cache and cache[kind][0] == key:
                return cache[kind][1]
            refs, vecs = [], []
            for r in c.execute("select ref, vec from vectors where kind=?", (kind,)):
                refs.append(r["ref"])
                vecs.append(_unpack(r["vec"]))
        cache[kind] = (key, (refs, vecs))
        return refs, vecs

    def _nearest(self, q: list[float], keep: Callable[[str], bool], n: int, exclude: str = "") -> list[tuple[int, float]]:
        ids, vecs = self._vectors()
        if not ids or len(vecs[0]) != len(q):
            return []
        scored = sorted(((math.sumprod(q, v), cid) for cid, v in zip(ids, vecs)), reverse=True)
        with self._db() as c:
            paths = {r["id"]: r["path"] for r in c.execute("select id, path from chunks")}
        out = []
        for s, cid in scored:
            p = paths.get(cid)
            if p and p != exclude and keep(p):
                out.append((cid, s))
                if len(out) >= n:
                    break
        return out

    def _by_ids(self, ids: list[int]) -> dict[int, Hit]:
        if not ids:
            return {}
        with self._db() as c:
            rows = c.execute(f"select id, path, heading, text, 0.0 as score from chunks where id in ({','.join('?' * len(ids))})",
                             ids).fetchall()
            return {h.id: h for h in self._hits(c, rows)}

    async def _query_vector(self, query: str, embedder) -> list[float] | None:
        """The question as a vector, or None when meaning search can't run: no embedder, another model's vectors, no
        vectors yet, or the embedder failing on the question (the caller then falls back to words)."""
        with self._db() as c:
            model = self._meta(c).get("model")
        if embedder is None or model != getattr(embedder, "name", None) or not (query or "").strip():
            return None
        try:
            return _normal((await embedder.embed([query], kind="query"))[0])  # a question, not a note: Gemma's prefix differs
        except Exception:  # noqa: BLE001
            return None

    async def search(self, query: str, k: int = 8, embedder=None, folder: str | None = None, since: str | None = None,
                     tags: list[str] | None = None) -> list[Hit]:
        """Note passages nearest the question by meaning when an embedder and vectors are there (decided 14 Oct 2026:
        no merging with word hits, which pulled in noise); the keyword hits otherwise."""
        with self._db() as c:
            keep = self._keep(c, folder, since, tags)
        q = await self._query_vector(query, embedder)
        if q is None or not self._vectors()[0]:
            return self.keyword(query, k=k, folder=folder, since=since, tags=tags)
        near = self._nearest(q, keep, k)
        hits = self._by_ids([cid for cid, _ in near])
        return [replace(hits[cid], score=s) for cid, s in near if cid in hits]

    async def search_all(self, query: str, k: int = 12, embedder=None, only: str | None = None, people: list[str] | None = None,
                         place: str | None = None, since: str | None = None, until: str | None = None,
                         album: str | None = None, most_pictures: int = 100_000) -> list[AnyHit]:
        """One lookup over notes and pictures, like Spotlight: by meaning when an embedder and vectors are there (one
        vector per question against every vector, notes and pictures on the same scale, ordered by likeness), by words
        otherwise (notes first, then pictures). only: "docs", "media", "photos" or "videos" narrows the kinds; the
        picture filters (people, place, since, until, album) apply after the lookup. An empty question with filters
        lists pictures newest first.
          "goa beach", meaning on          -> the trip note's passages and the beach photo, best first
          "", people=["Dev"], only="media"  -> Dev's pictures, newest first"""
        kinds = _kinds_for(only)
        keep = _photo_filter(_photo_kind(only), people, place, since, until, album)
        narrowed = bool(people or place or since or until or album or only in ("media", "photos", "videos"))
        if not (query or "").strip() and not narrowed:
            return []  # nothing asked, nothing narrowed: listing everything helps no one
        q = await self._query_vector(query, embedder)
        if q is not None and ("note" in kinds or "photo" in kinds) and self._vectors_of("chunk")[0] + self._vectors_of("photo")[0]:
            return self._nearest_all(q, kinds, keep, k, most_pictures)
        out: list[AnyHit] = []
        if "note" in kinds and (query or "").strip():
            out += [AnyHit("note", str(h.id), h.score, note=h) for h in self.keyword(query, k=k)]
        if "photo" in kinds:
            out += [AnyHit(h.kind, h.uuid, h.score, photo=h) for h in self.search_photos(query or "", k=most_pictures, kind=_photo_kind(only), people=people, place=place, since=since, until=until, album=album)]
        return out

    def _nearest_all(self, q: list[float], kinds: set[str], keep: Callable, k: int, most_pictures: int) -> list[AnyHit]:
        scored: list[tuple[float, str, str]] = []
        if "note" in kinds:
            refs, vecs = self._vectors_of("chunk")
            scored += [(math.sumprod(q, v), "chunk", ref) for ref, v in zip(refs, vecs) if len(v) == len(q)]
        if "photo" in kinds:
            refs, vecs = self._vectors_of("photo")
            scored += [(math.sumprod(q, v), "photo", ref) for ref, v in zip(refs, vecs) if len(v) == len(q)]
        scored.sort(reverse=True)
        with self._db() as c:
            paths = {r["id"]: r["path"] for r in c.execute("select id, path from chunks")}
            photos = {r["uuid"]: r for r in c.execute("select * from photos")}
        out: list[AnyHit] = []
        notes, pictures = 0, 0
        for s, kind, ref in scored:
            if kind == "chunk":
                if notes >= k or int(ref) not in paths:
                    continue
                notes += 1
                out.append(AnyHit("note", ref, s))
            else:
                row = photos.get(ref)
                if row is None or pictures >= most_pictures or not keep(row):
                    continue
                pictures += 1
                out.append(AnyHit(row["kind"], ref, s, photo=_photo_hit(row, s)))
            if notes >= k and pictures >= most_pictures:
                break
        by_id = self._by_ids([int(h.ref) for h in out if h.kind == "note"])
        return [replace(h, note=replace(by_id[int(h.ref)], score=h.score)) if h.kind == "note" else h
                for h in out if h.kind != "note" or int(h.ref) in by_id]

    async def related(self, note: str, k: int = 8) -> list[Hit]:
        """Notes near this one by meaning (when it has vectors), else by links, backlinks and shared tags."""
        p = self.resolve(note)
        if p is None:
            return []
        rel = p.relative_to(self.vault).as_posix()
        with self._db() as c:
            mine = [r["id"] for r in c.execute("select id from chunks where path=?", (rel,))]
            firsts = {r["path"]: r["id"] for r in c.execute("select path, min(id) as id from chunks group by path")}
        ids, vecs = self._vectors()
        index = dict(zip(ids, vecs))
        own = [index[i] for i in mine if i in index]
        if own:
            mean = _normal([sum(col) / len(own) for col in zip(*own)])
            best: dict[str, tuple[int, float]] = {}
            for cid, s in self._nearest(mean, lambda path: True, max(k * 6, 30), exclude=rel):
                path = self._by_ids([cid])[cid].path
                if path not in best:
                    best[path] = (cid, s)
            hits = self._by_ids([cid for cid, _ in best.values()])
            return [replace(hits[cid], score=s) for cid, s in sorted(best.values(), key=lambda x: -x[1])][:k]
        links = self.linked(note)
        counts: dict[str, int] = {}
        for group in ("links", "backlinks", "shared_tags"):
            for path in links[group]:
                counts[path] = counts.get(path, 0) + 1
        ranked = sorted(counts, key=lambda path: (-counts[path], path))[:k]
        hits = self._by_ids([firsts[path] for path in ranked if path in firsts])
        by_path = {h.path: h for h in hits.values()}
        return [replace(by_path[path], score=float(counts[path])) for path in ranked if path in by_path]

    def forget_meaning(self) -> None:
        """Meaning search was switched off: drop the vectors and say so in the status."""
        with self._db() as c:
            if c.execute("delete from vectors").rowcount:
                _bump(c)
            for key in ("model", "dims", "embed_error"):
                self._set(c, key, None)

    def status(self) -> dict:
        with self._db() as c:
            n = c.execute("select count(*) from notes").fetchone()[0]
            ch = c.execute("select count(*) from chunks").fetchone()[0]
            v = c.execute("select count(*) from vectors where kind='chunk'").fetchone()[0]
            photos = c.execute("select count(*) from photos where kind='photo'").fetchone()[0]
            videos = c.execute("select count(*) from photos where kind='video'").fetchone()[0]
            pv = c.execute("select count(*) from vectors where kind='photo'").fetchone()[0]
            meta = {r["key"]: r["value"] for r in c.execute("select key, value from meta")}
        return {"notes": n, "chunks": ch, "vectors": v, "model": meta.get("model"), "scanned_at": meta.get("scanned_at"),
                "embed_error": meta.get("embed_error"), "scan_warning": meta.get("scan_warning"),
                "photos": photos, "videos": videos, "photo_vectors": pv, "photos_at": meta.get("photos_at")}

    # ── photos and videos (odie.photos.library reads them; the rows come here) ──
    def index_photos(self, rows: Iterable, progress: Callable[[int, int], None] | None = None) -> dict:
        """Replace the photos with this read of the library (a few seconds for ten thousand). Vectors of pictures
        still there are kept; those of pictures gone are dropped."""
        rows = list(rows)
        with self._db() as c:
            before = {r["uuid"] for r in c.execute("select uuid from photos")}
            c.execute("delete from photos")
            c.execute("delete from photos_fts")
            for i, r in enumerate(rows):
                c.execute("insert into photos values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (r.uuid, r.kind, r.taken, json.dumps(r.people), json.dumps(r.labels), r.place, r.city, r.country,
                           json.dumps(r.albums), json.dumps(r.extras), int(r.favorite), int(r.screenshot), r.width, r.height,
                           r.thumb, r.big))
                extras = " ".join(v for values in r.extras.values() for v in values)
                c.execute("insert into photos_fts values (?,?,?,?,?,?,?)",
                          (r.uuid, " ".join(r.people), " ".join(r.labels), " ".join([r.place, r.city, r.country]),
                           " ".join(r.albums), extras, _when_words(r.taken)))
                if progress and (i % 500 == 0 or i + 1 == len(rows)):
                    progress(i + 1, len(rows))
            now = {r.uuid for r in rows}
            gone = [u for u in before if u not in now]
            for u in gone:
                c.execute("delete from vectors where kind='photo' and ref=?", (u,))
            if gone:
                _bump(c)
            self._set(c, "photos_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
        return {"photos": sum(1 for r in rows if r.kind == "photo"), "videos": sum(1 for r in rows if r.kind == "video"),
                "removed": len(gone)}

    def photo(self, uuid: str) -> dict | None:
        """One picture's row (the thumbnail route reads thumb and big from it), or None."""
        with self._db() as c:
            r = c.execute("select * from photos where uuid=?", (uuid,)).fetchone()
        return dict(r) if r else None

    def card_pictures(self) -> list[dict]:
        """Every photo that could go on an Up next card (odie.photos.cards): not a video, not a screenshot, and with a
        large copy on this Mac. Each as uuid, people and labels (JSON lists), extras (JSON), favorite and taken."""
        with self._db() as c:
            rows = c.execute("select uuid, people, labels, extras, favorite, taken from photos "
                             "where kind = 'photo' and not screenshot and coalesce(big, '') != ''").fetchall()
        return [dict(r) for r in rows]

    def photos_read_at(self) -> str:
        """When the photos were last read from the library ("" before the first read): a picture chosen from them
        stays right until this changes."""
        with self._db() as c:
            got = c.execute("select value from meta where key = 'photos_at'").fetchone()
        if got is None or got["value"] is None:
            return ""
        return str(got["value"])

    def search_photos(self, query: str, k: int = 8, kind: str | None = None, people: list[str] | None = None,
                      place: str | None = None, since: str | None = None, until: str | None = None,
                      album: str | None = None) -> list[PhotoHit]:
        """Pictures by words (people, what Photos saw, places, albums, dates and Apple's extras), narrowed by the filters;
        without words, the filters alone, newest first. Every name in people must be in the picture.
          "beach sunset"                       -> the beach sunset first
          "", people=["Asha"], since="2024-05-17" -> Asha's pictures from that day on, newest first"""
        words = [w.lower() for w in _WORD.findall(query or "") if w.lower() not in STOPWORDS]
        with self._db() as c:
            if words:
                match = " OR ".join(f'"{w}"' + ("*" if len(w) >= 4 else "") for w in dict.fromkeys(words))
                rows = c.execute("select p.*, -bm25(photos_fts) as score from photos_fts join photos p on p.uuid = photos_fts.uuid "
                                 "where photos_fts match ? order by bm25(photos_fts), p.taken desc", (match,)).fetchall()
            else:
                rows = c.execute("select *, 0.0 as score from photos order by taken desc").fetchall()
        keep = _photo_filter(kind, people, place, since, until, album)
        return [_photo_hit(r) for r in rows if keep(r)][:k]

    def forget_photos(self) -> None:
        """Photos were switched off: everything about them goes, their vectors too."""
        with self._db() as c:
            c.execute("delete from photos")
            c.execute("delete from photos_fts")
            if c.execute("delete from vectors where kind='photo'").rowcount:
                _bump(c)
            self._set(c, "photos_at", None)


def _when_words(taken: str) -> str:
    """A picture's date as the words someone would search by: "2024-05-16T11:09:23" -> "2024-05-16 16 May 2024 May 2024"."""
    if not taken or len(taken) < 10:
        return taken or ""
    year, month, day = taken[:4], int(taken[5:7]), int(taken[8:10])
    name = MONTHS[month - 1] if 1 <= month <= 12 else ""
    return f"{taken[:10]} {day} {name} {year} {name} {year}"


def _photo_filter(kind, people, place, since, until, album) -> Callable[[sqlite3.Row], bool]:
    """Whether a photos row passes the filters (each a plain, case-blind contains):
      kind "video" -> videos only; people ["Asha", "dev"] -> both named in it; place "goa" -> in its place, city or
      country; since "2024-05-17" -> taken that day or later; until the same the other way; album "goa" -> one of its albums."""
    wanted = [n.lower() for n in people or [] if n]
    place_q, album_q = (place or "").lower(), (album or "").lower()

    def keep(r: sqlite3.Row) -> bool:
        if kind and r["kind"] != kind:
            return False
        day = (r["taken"] or "")[:10]
        if since and day < since[:10]:
            return False
        if until and day > until[:10]:
            return False
        if wanted:
            names = [n.lower() for n in json.loads(r["people"] or "[]")]
            if not all(any(w in n for n in names) for w in wanted):
                return False
        if place_q and place_q not in " ".join([r["place"] or "", r["city"] or "", r["country"] or ""]).lower():
            return False
        if album_q and not any(album_q in a.lower() for a in json.loads(r["albums"] or "[]")):
            return False
        return True
    return keep


NOTEWORTHY = ("holidays", "landmarks", "pets", "detected_text", "events")  # not "trip": Apple only says "Trips"


def _kinds_for(only: str | None) -> set[str]:
    """Which kinds a search covers: only "docs" -> notes; "media", "photos", "videos" -> pictures; anything else -> both."""
    if only == "docs":
        return {"note"}
    if only in ("media", "photos", "videos"):
        return {"photo"}
    return {"note", "photo"}


def _photo_kind(only: str | None) -> str | None:
    """"photos" -> "photo", "videos" -> "video", else None (both)."""
    return {"photos": "photo", "videos": "video"}.get(only or "")


def picture_words(r: sqlite3.Row) -> str:
    """A picture's words for its vector: who, what Photos saw, where, which albums, when, and Apple's extras.
      Asha; Beach, Sea; Goa, India; Goa 2024; 2024-05-16 -> "Asha · Beach, Sea · Goa, India · Goa 2024 · 16 May 2024" """
    parts = []
    people = json.loads(r["people"] or "[]")
    if people:
        parts.append(", ".join(people))
    labels = json.loads(r["labels"] or "[]")
    if labels:
        parts.append(", ".join(labels[:12]))
    if r["place"]:
        parts.append(r["place"])
    albums = json.loads(r["albums"] or "[]")
    if albums:
        parts.append(", ".join(albums))
    taken = r["taken"] or ""
    if len(taken) >= 10:
        try:
            parts.append(date.fromisoformat(taken[:10]).strftime("%-d %B %Y"))
        except ValueError:
            parts.append(taken[:10])
    extras = json.loads(r["extras"] or "{}")
    worth = [v for key in NOTEWORTHY for v in extras.get(key, [])][:6]
    if worth:
        parts.append(", ".join(worth))
    if r["kind"] == "video":
        parts.append("video")
    return " · ".join(parts) or r["kind"]


IMAGE_FILES = (".jpeg", ".jpg", ".png", ".heic", ".heif", ".tiff", ".tif", ".gif", ".webp", ".bmp")


def picture_file(r: sqlite3.Row) -> str | None:
    """The copy the model should look at: the big one when it's on disk and is a still image, else the thumbnail,
    else None. A row read before 14 Oct 2026 may name a movie file as its big copy: the thumbnail is used instead."""
    for key in ("big", "thumb"):
        path = r[key]
        if path and path.lower().endswith(IMAGE_FILES) and Path(path).is_file():
            return path
    return None


def _photo_hit(r: sqlite3.Row, score: float = 0.0) -> PhotoHit:
    """A photos row as a hit; the score comes with a keyword row (its bm25) or is given (a vector lookup)."""
    extras = json.loads(r["extras"] or "{}")
    worth = [v for key in NOTEWORTHY for v in extras.get(key, [])][:6]
    if "score" in r.keys():
        score = float(r["score"])
    return PhotoHit(r["uuid"], r["kind"], (r["taken"] or "")[:10], r["place"] or "", json.loads(r["people"] or "[]"),
                    json.loads(r["labels"] or "[]"), json.loads(r["albums"] or "[]"), worth, bool(r["thumb"]), score)


def _normal(v: list[float]) -> list[float]:
    n = math.sqrt(math.sumprod(v, v)) or 1.0
    return [x / n for x in v]


def _pack(v: list[float]) -> bytes:
    return array("f", _normal(v)).tobytes()


def _unpack(blob: bytes) -> array:
    a = array("f")  # kept as float32: a Python list of floats is about seven times the memory
    a.frombytes(blob)
    return a


def _bump(c: sqlite3.Connection) -> None:
    """The vectors changed (rows can come back under the same ids): any cached copy is stale."""
    c.execute("insert into meta values ('vectors_version', '1') on conflict(key) do update set value = cast(value as integer) + 1")
