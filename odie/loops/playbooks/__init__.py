"""Playbooks: how Odie handles one kind of loop (proactive design §7, §9). A playbook is a skill: a folder here with a
SKILL.md whose front matter says which loops it takes and each step's tier (0 silent, 1 act then tell, 2 prepare and
wait for a tap; 3, the red lines, is never allowed), and whose text is what the model reads when it chooses. Phase 1
has one, github-pr, read-only."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

HERE = Path(__file__).parent
NEVER = 3  # tier 3 is never from the background, so no playbook may declare it


@dataclass(frozen=True)
class Playbook:
    name: str
    description: str
    takes: tuple[str, ...]
    steps: dict
    text: str


def load(path: Path) -> Playbook:
    """One playbook from its SKILL.md. A step with a tier outside 0-2 raises ValueError."""
    raw = path.read_text()
    _, front, body = raw.split("---", 2)
    meta = yaml.safe_load(front) or {}
    steps = {str(name): int(tier) for name, tier in (meta.get("steps") or {}).items()}
    for name, tier in steps.items():
        if tier < 0 or tier >= NEVER:
            raise ValueError(f"{path.parent.name}: step {name} declares tier {tier}; a playbook may use 0 to 2")
    takes = tuple(str(k).strip().lower() for k in meta.get("takes") or [])
    return Playbook(str(meta.get("name") or path.parent.name), str(meta.get("description") or ""), takes, steps,
                    body.strip())


def installed() -> dict[str, Playbook]:
    out = {}
    for skill in sorted(HERE.glob("*/SKILL.md")):
        book = load(skill)
        out[book.name] = book
    return out


def get(name: str) -> Playbook | None:
    return installed().get(name or "")


def for_kind(kind: str) -> Playbook | None:
    """The playbook that takes this kind of loop: "pull request" -> github-pr; "Issue" -> github-pr; "bill" -> None
    (no playbook yet: the loop is only followed)."""
    wanted = (kind or "").strip().lower()
    for book in installed().values():
        if wanted in book.takes:
            return book
    return None
