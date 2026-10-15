"""A note, read for the index: its title, aliases, tags and links, and its text split into chunks by headings (small
sections merged, big ones split at paragraphs) so a search hit is a passage, not a whole note."""
from __future__ import annotations

import re
from dataclasses import dataclass

MIN_WORDS = 300
MAX_WORDS = 800

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_TAG = re.compile(r"(?<![\w#&/])#([A-Za-z][\w/-]*)")
_FENCE = re.compile(r"^(```|~~~)")


@dataclass(frozen=True)
class Chunk:
    heading: str        # the section's heading path, e.g. "Trip > Day 2" ("" before the first heading)
    text: str


@dataclass(frozen=True)
class Parsed:
    title: str
    aliases: tuple[str, ...]
    tags: tuple[str, ...]
    links: tuple[str, ...]
    chunks: tuple[Chunk, ...]


def _frontmatter(text: str) -> tuple[dict[str, list[str]], str]:
    """The YAML frontmatter's simple keys (scalars, [a, b] and "- a" lists), and the body after it."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    meta: dict[str, list[str]] = {}
    key = None
    for line in text[4:end].splitlines():
        if m := re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line):
            key, value = m.group(1).lower(), m.group(2).strip()
            if value.startswith("[") and value.endswith("]"):
                meta[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            else:
                meta[key] = [value.strip("'\"")] if value else []
        elif key and (m := re.match(r"^\s*-\s+(.+)$", line)):
            meta.setdefault(key, []).append(m.group(1).strip().strip("'\""))
    body = text[end + 4:]
    return meta, body[1:] if body.startswith("\n") else body


def _sections(body: str) -> list[tuple[str, str]]:
    """(heading path, text) per heading; headings inside code fences don't count."""
    out: list[tuple[str, str]] = []
    path: list[tuple[int, str]] = []
    lines: list[str] = []
    heading = ""
    fenced = False
    for line in body.splitlines():
        if _FENCE.match(line.strip()):
            fenced = not fenced
        m = None if fenced else _HEADING.match(line)
        if m:
            out.append((heading, "\n".join(lines).strip()))
            level, title = len(m.group(1)), m.group(2).strip()
            path = [(lv, t) for lv, t in path if lv < level] + [(level, title)]
            heading = " > ".join(t for _, t in path)
            lines = [line]
        else:
            lines.append(line)
    out.append((heading, "\n".join(lines).strip()))
    return [(h, t) for h, t in out if t or h]


def _words(text: str) -> int:
    return len(text.split())


def _split(heading: str, text: str) -> list[Chunk]:
    """A section over MAX_WORDS, cut at paragraphs (a paragraph that is itself too long, at words)."""
    paras: list[str] = []
    for p in re.split(r"\n\s*\n", text):
        words = p.split()
        while len(words) > MAX_WORDS:
            paras.append(" ".join(words[:MAX_WORDS]))
            words = words[MAX_WORDS:]
        if words:
            paras.append(p if len(p.split()) <= MAX_WORDS else " ".join(words))
    out, cur = [], []
    for p in paras:
        if cur and _words("\n\n".join([*cur, p])) > MAX_WORDS:
            out.append(Chunk(heading, "\n\n".join(cur)))
            cur = []
        cur.append(p)
    if cur:
        out.append(Chunk(heading, "\n\n".join(cur)))
    return out


def _chunks(sections: list[tuple[str, str]]) -> list[Chunk]:
    out: list[Chunk] = []
    heading, parts = "", []

    def flush() -> None:
        nonlocal heading, parts
        text = "\n\n".join(p for p in parts if p).strip()
        if text and not all(_HEADING.match(ln) for ln in text.splitlines() if ln.strip()):
            out.append(Chunk(heading, text))
        heading, parts = "", []

    for h, text in sections:
        if _words(text) > MAX_WORDS:
            flush()
            out.extend(_split(h, text))
            continue
        if parts and _words("\n\n".join([*parts, text])) > MAX_WORDS:
            flush()
        if not parts:
            heading = h
        parts.append(text)
        if _words("\n\n".join(parts)) >= MIN_WORDS:
            flush()
    flush()
    return out


def _unique(items) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for i in items:
        if i and i not in seen:
            seen[i] = None
    return tuple(seen)


def parse(text: str, name: str) -> Parsed:
    meta, body = _frontmatter(text)
    first_h1 = next((m.group(2).strip() for line in body.splitlines() if (m := _HEADING.match(line)) and len(m.group(1)) == 1), "")
    title = (meta.get("title") or [""])[0] or first_h1 or name
    tags = _unique([t.lstrip("#").lower() for t in meta.get("tags", [])] + [t.lower() for t in _TAG.findall(body)])
    links = _unique(m.group(1).strip().removesuffix(".md") for m in _LINK.finditer(body))
    return Parsed(title, _unique(meta.get("aliases", [])), tags, links, tuple(_chunks(_sections(body))))
