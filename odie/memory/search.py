"""Keyword search over memory entries (BM25, light stemming). Adapted from the obsidian-memory plugin."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from odie.memory.store import Entry

STOPWORDS = frozenset(
    "a an and are as at be but by can could did do does for from had has have how i if in into is it its me my of on or "
    "our so than that the their them then there these they this to was we were what when where which who why will with "
    "would you your about any all just also some please tell know remember recall".split())
TOKEN_RE = re.compile(r"[\w][\w'-]*", re.UNICODE)
POSSESSIVE_RE = re.compile(r"['’]s\b", re.IGNORECASE)
K1, B = 1.2, 0.75


def stem(word: str) -> str:
    for suffix in ("ingly", "edly", "ing", "ies", "ied", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            return base + "y" if suffix in ("ies", "ied") else base
    return word


def terms(text: str) -> list[str]:
    text = POSSESSIVE_RE.sub("", text)
    return [stem(t) for t in (w.casefold().strip("'-") for w in TOKEN_RE.findall(text)) if t and t not in STOPWORDS and len(t) > 1]


@dataclass
class Hit:
    entry: Entry
    score: float
    matched: int


def _doc_terms(e: Entry) -> list[str]:
    head = terms(f"{e.title} {e.topic}")
    return head + head + terms(e.body)


def search(entries: list[Entry], query: str, limit: int = 5, min_matched: int = 1) -> list[Hit]:
    q = list(dict.fromkeys(terms(query)))
    if not q or not entries:
        return []
    docs = [Counter(_doc_terms(e)) for e in entries]
    lengths = [sum(d.values()) for d in docs]
    avg = (sum(lengths) / len(lengths)) or 1.0
    n = len(docs)
    df = {t: sum(1 for d in docs if t in d) for t in q}
    hits: list[Hit] = []
    for e, d, length in zip(entries, docs, lengths, strict=True):
        score, matched = 0.0, 0
        for t in q:
            tf = d.get(t, 0)
            if not tf:
                continue
            matched += 1
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / avg))
        if matched >= min_matched:
            hits.append(Hit(e, score, matched))
    hits.sort(key=lambda h: (h.score, h.entry.date), reverse=True)
    return hits[:limit]


def prefetch_hits(entries: list[Entry], query: str, limit: int) -> list[Hit]:
    """Stricter than the tool: two shared content words, or one word from the entry's title."""
    q = set(terms(query))
    need = 2 if len(q) >= 2 else 1
    hits = search(entries, query, limit=max(limit * 5, 20), min_matched=1)
    kept = [h for h in hits if h.matched >= need or q & set(terms(h.entry.title))]
    return kept[:limit]
