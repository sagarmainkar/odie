"""Recall's index: past chats and memory entries as passages in odie-index.db, searchable by words (FTS5) and
by meaning (vectors).

It shares the file with the notes index (VaultIndex) and the same vectors/meta tables, but has its own passages and
passages_fts tables, so it never touches the notes' tables. A passage's vector (for meaning search) is
the vectors row with the same kind and ref.

passages_fts is kept in step by hand: its rowid is the passage's rowid, and every insert or delete of a passage does
the same to its fts row."""
from __future__ import annotations

import hashlib
import math
import sqlite3
from array import array
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from odie.memory.search import STOPWORDS
from odie.memory.store import Entry, norm
from odie.recall.chats import Exchange
from odie.vault.index import _WORD, _bump, _normal, _pack, _unpack

PASSAGE_CHARS = 2000  # a recall passage is never longer than this
KINDS = ("chat", "memory")  # the passage kinds that have vectors; the notes' kinds ("chunk", "photo") are not ours

SCHEMA = """
create table if not exists passages (kind text not null, ref text not null, day text, session_id text, title text,
                                     text text, sha text, primary key (kind, ref));
create virtual table if not exists passages_fts using fts5(title, text, tokenize='unicode61 remove_diacritics 2');
create table if not exists vectors (kind text not null, ref text not null, vec blob not null, primary key (kind, ref));
create table if not exists meta (key text primary key, value text);
"""


@dataclass(frozen=True)
class RecallHit:
    kind: str  # "chat" or "memory"
    ref: str
    day: str  # ISO date: the chat's day, or the memory's own date
    title: str
    text: str
    score: float  # higher is a better match


class RecallIndex:
    def __init__(self, db: Path) -> None:
        self.db_path = Path(db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as c:
            c.executescript(SCHEMA)

    def _db(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("pragma journal_mode=wal")
        return c

    # ── writing ──
    def _add(self, c: sqlite3.Connection, kind: str, ref: str, day: str, session_id: str, title: str, text: str,
             sha: str) -> None:
        cur = c.execute("insert into passages values (?,?,?,?,?,?,?)", (kind, ref, day, session_id, title, text, sha))
        c.execute("insert into passages_fts(rowid, title, text) values (?,?,?)", (cur.lastrowid, title, text))

    def _drop(self, c: sqlite3.Connection, kind: str, ref: str) -> None:
        """Remove a passage, its words (fts row) and its vector."""
        row = c.execute("select rowid from passages where kind=? and ref=?", (kind, ref)).fetchone()
        if row is not None:
            c.execute("delete from passages_fts where rowid=?", (row["rowid"],))
            c.execute("delete from passages where kind=? and ref=?", (kind, ref))
        if c.execute("delete from vectors where kind=? and ref=?", (kind, ref)).rowcount:
            _bump(c)

    def add_exchanges(self, ex: list[Exchange]) -> int:
        """Index chat exchanges; one already indexed (same session and message time) is skipped. Returns how many
        were new."""
        added = 0
        with self._db() as c:
            for e in ex:
                ref = f"{e.session_id}@{e.ts:.3f}"
                known = c.execute("select 1 from passages where kind='chat' and ref=?", (ref,)).fetchone()
                if known is not None:
                    continue
                sha = hashlib.sha1(e.text.encode()).hexdigest()
                self._add(c, "chat", ref, e.day, e.session_id, f"chat {e.day}", e.text[:PASSAGE_CHARS], sha)
                added += 1
        return added

    def last_chat_ts(self, session_id: str) -> float:
        """The message time of the newest exchange indexed for this session, or 0.0 when there is none.
          chat-book indexed up to 3 Nov 15:00 -> that time, so the next pass reads from there and picks up 4 Nov
          never indexed                         -> 0.0 (read the whole session)"""
        with self._db() as c:
            rows = c.execute("select ref from passages where kind='chat' and session_id=?", (session_id,)).fetchall()
        if not rows:
            return 0.0
        # a ref is "<session>@<ts>"; the time is read as a number, since text order puts "9.0" after "10.0"
        stamps = [float(r["ref"].rsplit("@", 1)[1]) for r in rows]
        return max(stamps)

    def sync_memories(self, entries: list[Entry]) -> int:
        """Make the memory passages match the memory file. Returns how many were added or replaced.
          a new title                 -> added
          same title, changed body    -> row replaced, its old vector dropped
          same title, same body       -> left alone
          a title no longer in file   -> row, words and vector deleted"""
        wanted = {norm(e.title): e for e in entries}
        written = 0
        with self._db() as c:
            have = {r["ref"]: r["sha"] for r in c.execute("select ref, sha from passages where kind='memory'")}
            for ref in have:
                if ref not in wanted:
                    self._drop(c, "memory", ref)
            for ref, entry in wanted.items():
                sha = hashlib.sha1(entry.body.encode()).hexdigest()
                if have.get(ref) == sha:
                    continue
                self._drop(c, "memory", ref)
                self._add(c, "memory", ref, entry.date, "", entry.title, entry.body[:PASSAGE_CHARS], sha)
                written += 1
        return written

    def chats_read_until(self) -> float:
        """The time the chats were last read up to (a local midnight), or 0.0 when they never were."""
        with self._db() as c:
            value = self._meta(c).get("recall_chats_until")
        if value is None:
            return 0.0
        return float(value)

    def mark_chats_read_until(self, ts: float) -> None:
        with self._db() as c:
            self._set(c, "recall_chats_until", repr(ts))

    # ── searching by words ──
    def keyword(self, query: str, k: int = 8, since: str | None = None, until: str | None = None) -> list[RecallHit]:
        """The best word matches, best first, and on equal scores the newest day first. since / until are ISO days
        (inclusive): since="2026-11-04" drops a 3 Nov chat; a query of only stopwords finds nothing."""
        words = [w.lower() for w in _WORD.findall(query or "") if w.lower() not in STOPWORDS]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' + ("*" if len(w) >= 4 else "") for w in dict.fromkeys(words))
        sql = ("select p.kind, p.ref, p.day, p.title, p.text, -bm25(passages_fts) as score from passages_fts "
               "join passages p on p.rowid = passages_fts.rowid where passages_fts match ?")
        args: list = [match]
        if since:
            sql += " and p.day >= ?"
            args.append(since)
        if until:
            sql += " and p.day <= ?"
            args.append(until)
        sql += " order by bm25(passages_fts), p.day desc, p.ref desc limit ?"
        args.append(k)
        with self._db() as c:
            rows = c.execute(sql, args).fetchall()
        return [RecallHit(r["kind"], r["ref"], r["day"], r["title"], r["text"], r["score"]) for r in rows]

    # ── searching by meaning ──
    def _meta(self, c: sqlite3.Connection) -> dict[str, str]:
        return {r["key"]: r["value"] for r in c.execute("select key, value from meta")}

    def _set(self, c: sqlite3.Connection, key: str, value: str | None) -> None:
        if value is None:
            c.execute("delete from meta where key=?", (key,))
        else:
            c.execute("insert or replace into meta values (?,?)", (key, value))

    async def embed_pending(self, embedder, batch: int = 32, progress: Callable[[int, int], None] | None = None) -> int:
        """Embed the chat and memory passages that have no vector. Returns how many were embedded.
          index never embedded, model unset      -> the model is set to the embedder's name, every passage embedded
          passage without a vector, same model   -> embedded (also after the notes' pass cleared every vector)
          index's model is another name          -> nothing embedded, 0: the notes' pass (VaultIndex.embed_pending)
                                                    owns a model switch and clears all vectors, then this one runs again
          embedder fails                         -> the run stops, meta.recall_embed_error says why, the next run
                                                    tries again (the notes keep their own embed_error, never touched)"""
        with self._db() as c:
            model = self._meta(c).get("model")
            if model is not None and model != embedder.name:
                return 0
            if model is None:
                self._set(c, "model", embedder.name)
            pending = c.execute(
                "select kind, ref, title, text from passages p where kind in ('chat', 'memory') and not exists "
                "(select 1 from vectors v where v.kind = p.kind and v.ref = p.ref) order by day, ref").fetchall()
        done = 0
        for i in range(0, len(pending), batch):
            rows = pending[i:i + batch]
            texts = [{"title": r["title"], "text": r["text"]} for r in rows]
            try:
                vecs = await embedder.embed(texts)
            except Exception as e:  # noqa: BLE001
                with self._db() as c:
                    self._set(c, "recall_embed_error", f"{type(e).__name__}: {e}"[:300])
                return done
            stored = self._store_vectors([(r["kind"], r["ref"]) for r in rows], vecs)
            done += stored
            if stored < len(rows):  # a vector of the wrong size was refused; the error is recorded
                return done
            if progress:
                progress(min(i + batch, len(pending)), len(pending))
        with self._db() as c:
            self._set(c, "recall_embed_error", None)
        return done

    def embed_error(self) -> str | None:
        """Why recall's last embedding run stopped, or None when it finished (or never ran)."""
        with self._db() as c:
            return self._meta(c).get("recall_embed_error")

    def adopt_model(self, embedder) -> bool:
        """Whether recall had to switch to this embedder's model; when it did, its own old vectors are dropped so the
        next embed_pending reads every chat and memory again. Only for an index with no notes or photos: with those,
        the notes' pass (VaultIndex.embed_pending) owns a switch and clears every kind's vectors itself.
          model "old", embedder "new"   -> True: chat/memory vectors deleted, model "new", dims cleared when no other
                                           kind's vectors remain (a photo's would keep it)
          model unset, embedder "new"   -> True: model "new"
          model "new", embedder "new"   -> False: nothing changes"""
        with self._db() as c:
            if self._meta(c).get("model") == embedder.name:
                return False
            c.execute("delete from vectors where kind in ('chat', 'memory')")
            self._set(c, "model", embedder.name)
            others = c.execute("select count(*) from vectors").fetchone()[0]
            if others == 0:
                self._set(c, "dims", None)
            _bump(c)
        return True

    def _store_vectors(self, keys: list[tuple[str, str]], vecs: list[list[float]]) -> int:
        """Keep these vectors and return how many were kept. The first vector sets the index's vector size; a vector
        of another size than the notes' pass set is refused, and so is the rest of the run, because the notes' pass
        is the one that starts the index over (it clears every kind), not this one."""
        kept = 0
        with self._db() as c:
            dims = self._meta(c).get("dims")
            for (kind, ref), v in zip(keys, vecs):
                if dims and int(dims) != len(v):
                    self._set(c, "recall_embed_error", f"vector size {len(v)} differs from the index's {dims}"[:300])
                    break
                if not dims:
                    dims = str(len(v))
                    self._set(c, "dims", dims)
                c.execute("insert or replace into vectors values (?, ?, ?)", (kind, ref, _pack(v)))
                kept += 1
            _bump(c)
        return kept

    def _vectors_of(self, kind: str) -> tuple[list[str], list[array]]:
        """Every vector of one kind, cached until the vectors change."""
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

    async def _query_vector(self, query: str, embedder) -> list[float] | None:
        """The question as a vector, or None when meaning search can't run:
          no embedder, or a blank question          -> None
          the index holds another model's vectors   -> None (a vector of one model means nothing to another)
          the embedder fails on the question        -> None
          embedder "fake" and index model "fake"    -> the normalised vector"""
        if embedder is None or not (query or "").strip():
            return None
        with self._db() as c:
            model = self._meta(c).get("model")
        if model != getattr(embedder, "name", None):
            return None
        try:
            return _normal((await embedder.embed([query], kind="query"))[0])
        except Exception:  # noqa: BLE001
            return None

    async def search(self, query: str, k: int = 8, embedder=None, since: str | None = None,
                     until: str | None = None) -> list[RecallHit]:
        """Passages nearest the question by meaning when an embedder and vectors are there, else the word matches.
        Never both (the owner's D-057: mixed scores pulled in noise).
          "bill payment", embedder fits, vectors exist -> the invoice chat and the rent memory, by likeness
          same question, no embedder / another model / embedder down / no vectors -> keyword("bill payment")
        since / until are ISO days, inclusive, as in keyword."""
        q = await self._query_vector(query, embedder)
        if q is None:
            return self.keyword(query, k=k, since=since, until=until)
        days = self._days(since, until)
        scored: list[tuple[float, str, str]] = []
        for kind in KINDS:
            refs, vecs = self._vectors_of(kind)
            for ref, v in zip(refs, vecs):
                if (kind, ref) in days and len(v) == len(q):
                    scored.append((math.sumprod(q, v), kind, ref))
        if not scored:
            return self.keyword(query, k=k, since=since, until=until)
        # best likeness first; on equal scores the newest day, then the newest ref
        scored.sort(key=lambda s: (s[0], days[(s[1], s[2])], s[2]), reverse=True)
        best = scored[:k]
        with self._db() as c:
            hits = []
            for score, kind, ref in best:
                r = c.execute("select kind, ref, day, title, text from passages where kind=? and ref=?",
                              (kind, ref)).fetchone()
                hits.append(RecallHit(r["kind"], r["ref"], r["day"], r["title"], r["text"], score))
        return hits

    def _days(self, since: str | None, until: str | None) -> dict[tuple[str, str], str]:
        """The passages that pass the day filter, each with its day: since="2026-11-04" leaves out a 3 Nov chat."""
        sql = "select kind, ref, day from passages where kind in ('chat', 'memory')"
        args: list = []
        if since:
            sql += " and day >= ?"
            args.append(since)
        if until:
            sql += " and day <= ?"
            args.append(until)
        with self._db() as c:
            return {(r["kind"], r["ref"]): r["day"] for r in c.execute(sql, args)}
