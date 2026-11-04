"""Recall's index: past chats and memory entries as passages in odie-index.db, searchable by words (FTS5).

It shares the file with the notes index (VaultIndex) and the same vectors/meta tables, but has its own passages and
passages_fts tables, so it never touches the notes' tables. A passage's vector (added later, for meaning search) is
the vectors row with the same kind and ref.

passages_fts is kept in step by hand: its rowid is the passage's rowid, and every insert or delete of a passage does
the same to its fts row."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from odie.memory.search import STOPWORDS
from odie.memory.store import Entry, norm
from odie.recall.chats import Exchange
from odie.vault.index import _WORD, _bump

PASSAGE_CHARS = 2000  # a recall passage is never longer than this

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
