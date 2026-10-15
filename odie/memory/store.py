"""Odie's long-term memory: one Markdown file (in the vault when there is one).

    ## Topic
    ### Title (YYYY-MM-DD)
    body

Adapted from the author's earlier Obsidian memory plugin.
Writes replace one entry at a time, keep the previous text in an append-only history file, and go
through a lock plus an atomic rename, so Obsidian edits and Odie writes do not clobber each other.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

INBOX = "Inbox"
MAX_ENTRY_CHARS = 2000
MAX_TITLE_CHARS = 90
DATED_RE = re.compile(r"^(?P<title>.*?)\s*\((?P<date>\d{4}-\d{2}-\d{2})\)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_IN_BODY_RE = re.compile(r"^(#{1,3})(\s)", re.MULTILINE)
TOPIC_TAG_RE = re.compile(r"\s*\[[^\]]*\]\s*$")


def today() -> str:
    return dt.date.today().isoformat()


def bare_title(title: str) -> str:
    title = TOPIC_TAG_RE.sub("", str(title or "").strip())
    m = DATED_RE.match(title)
    return (m.group("title") if m else title).strip()


def norm(title: str) -> str:
    return " ".join(bare_title(title).split()).casefold()


@dataclass
class Entry:
    topic: str
    title: str
    date: str
    body: str

    @property
    def heading(self) -> str:
        return f"{self.title} ({self.date})" if self.date else self.title

    def render(self) -> str:
        return f"### {self.heading}\n\n{self.body.strip()}\n"


@dataclass
class Topic:
    name: str
    intro: str = ""
    entries: list[Entry] = field(default_factory=list)


@dataclass
class MemoryDoc:
    preamble: str
    topics: list[Topic] = field(default_factory=list)

    def entries(self) -> list[Entry]:
        return [e for t in self.topics for e in t.entries]

    def newest_first(self) -> list[Entry]:
        indexed = list(enumerate(self.entries()))
        indexed.sort(key=lambda p: (p[1].date, p[0]), reverse=True)
        return [e for _, e in indexed]

    def find(self, title: str) -> Entry | None:
        key = norm(title)
        if not key:
            return None
        entries = self.entries()
        exact = [e for e in entries if norm(e.title) == key]
        if exact:
            return exact[0]
        partial = [e for e in entries if key in norm(e.title)]
        return partial[0] if len(partial) == 1 else None

    def topic(self, name: str) -> Topic | None:
        key = " ".join(name.split()).casefold()
        return next((t for t in self.topics if t.name.casefold() == key), None)

    def upsert(self, title: str, content: str, topic: str | None = None, date: str | None = None,
               append: bool = False) -> tuple[Entry, Entry | None]:
        title = clean_title(title)
        if not title:
            raise ValueError("title is required")
        body = clean_body(content)
        if not body:
            raise ValueError("content is required")
        previous = self.find(title)
        topic_name = " ".join((topic or "").split()) or (previous.topic if previous else INBOX)
        if previous is not None and append:
            body = clean_body(previous.body.rstrip() + "\n\n" + body)
        entry = Entry(topic_name, previous.title if previous else title, date or today(), body)
        if previous is not None:
            self._remove(previous)
        t = self.topic(topic_name)
        if t is None:
            t = Topic(topic_name)
            self.topics.append(t)
        t.entries.append(entry)
        return entry, previous

    def _remove(self, entry: Entry) -> None:
        for t in self.topics:
            if entry in t.entries:
                t.entries.remove(entry)

    def render(self) -> str:
        parts = [self.preamble.rstrip() + "\n"]
        for t in self.topics:
            block = [f"## {t.name}\n"]
            if t.intro.strip():
                block.append(t.intro.strip() + "\n")
            block.extend(e.render() for e in t.entries)
            parts.append("\n".join(block))
        return "\n".join(parts).rstrip() + "\n"


def clean_title(title: str) -> str:
    title = " ".join(bare_title(str(title or "").replace("#", "")).split())
    return title.lstrip("§•*-– ").strip()[:MAX_TITLE_CHARS].strip()


def clean_body(content: str) -> str:
    body = HEADING_IN_BODY_RE.sub(r"####\2", str(content or "").strip())
    return body[: MAX_ENTRY_CHARS - 1].rstrip() + "…" if len(body) > MAX_ENTRY_CHARS else body


def parse(text: str) -> MemoryDoc:
    doc = MemoryDoc(preamble="")
    preamble: list[str] = []
    topic: Topic | None = None
    entry_lines: list[str] | None = None
    entry_head = ""
    in_fence = False

    def flush_entry() -> None:
        nonlocal entry_lines
        if topic is not None and entry_lines is not None:
            m = DATED_RE.match(entry_head)
            title, date = (m.group("title"), m.group("date")) if m else (entry_head, "")
            topic.entries.append(Entry(topic.name, title.strip(), date, "\n".join(entry_lines).strip()))
        entry_lines = None

    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
        if not in_fence and line.startswith("## ") and not line.startswith("### "):
            flush_entry()
            topic = Topic(line[3:].strip())
            doc.topics.append(topic)
            continue
        if not in_fence and line.startswith("### ") and topic is not None:
            flush_entry()
            entry_head = line[4:].strip()
            entry_lines = []
            continue
        if entry_lines is not None:
            entry_lines.append(line)
        elif topic is not None:
            topic.intro = (topic.intro + "\n" + line).strip("\n")
        else:
            preamble.append(line)
    flush_entry()
    doc.preamble = "\n".join(preamble).rstrip() + "\n"
    return doc


def template(profile: str) -> str:
    return (f"---\ntitle: {profile} — long-term memory\ntype: agent-memory\nprofile: {profile}\ncreated: {today()}\n"
            f"tags: [agent-memory, odie]\n---\n\n# {profile} — long-term memory\n\n"
            "> [!info] Maintained by Odie\n> Topics are `##` headings; each memory is a dated `###` entry. Edit freely in Obsidian.\n"
            "> Odie replaces whole entries and keeps earlier versions in `.history/`. New memories without a topic land in the Inbox.\n")


class MemoryFile:
    def __init__(self, path: Path, lock_path: Path, profile: str) -> None:
        self.path = path
        self.lock_path = lock_path
        self.profile = profile
        self.history_path = path.parent / ".history" / f"{path.stem}-history.md"

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> MemoryDoc:
        if not self.path.is_file():
            return parse(template(self.profile))
        return parse(self.path.read_text(encoding="utf-8"))

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def save(self, doc: MemoryDoc) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".odie-mem-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(doc.render())
        os.replace(tmp, self.path)

    def update(self, title: str, content: str, topic: str | None = None, source: str = "odie",
               append: bool = False) -> tuple[Entry, Entry | None]:
        from odie.signin.money import holds_financial
        if holds_financial(f"{title}\n{content}"):  # never, from chat or the review: card, UPI or bank details
            raise ValueError("I don't keep card, UPI or bank details in memory.")
        with self.locked():
            doc = self.load()
            entry, previous = doc.upsert(title, content, topic, append=append)
            if previous is not None:
                self._log_history(previous, entry, source)
            self.save(doc)
        return entry, previous

    def forget(self, title: str, source: str = "odie") -> Entry | None:
        """Removes one entry (its text is kept in the history file). None when no entry has that title."""
        with self.locked():
            doc = self.load()
            entry = doc.find(title)
            if entry is None:
                return None
            for t in doc.topics:
                t.entries = [e for e in t.entries if e is not entry]
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now().isoformat(timespec="seconds")
            with self.history_path.open("a", encoding="utf-8") as fh:
                fh.write(f"## {stamp} — forgotten by {source}: {entry.heading}\nTopic: {entry.topic}\n\n{entry.body.strip()}\n\n")
            self.save(doc)
        return entry

    def ensure(self) -> None:
        if not self.path.is_file():
            with self.locked():
                if not self.path.is_file():
                    self.save(parse(template(self.profile)))

    def _log_history(self, previous: Entry, new: Entry, source: str) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().isoformat(timespec="seconds")
        with self.history_path.open("a", encoding="utf-8") as fh:
            fh.write(f"## {stamp} — replaced by {source}: {previous.heading}\nTopic: {previous.topic} → {new.topic}\n\n{previous.body.strip()}\n\n")
