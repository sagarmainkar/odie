"""Save an install's conversations as Markdown, for showing someone what happened: the setup chat, then every chat
thread, oldest first. Anything that looks like a key is masked.

    scripts/conversation.sh first             ~/odie-runs/first  →  ~/odie-runs/first/logs/conversation.md
    scripts/conversation.sh ~/.odie           any Odie home
"""
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from odie.setup import keys  # Odie's own key catcher: the shapes it stops in setup are masked here

MASKED = "…(masked)"
LINK = re.compile(r"https?://[^\s\"'`)<>]+")


def mask(text: str) -> str:
    for _, rx in keys.SHAPES:
        text = rx.sub(MASKED, text)
    text = LINK.sub(lambda m: MASKED if keys.secret_link(m.group(0)) else m.group(0), text)
    return re.sub(r"[A-Za-z0-9_-]{8,}", lambda m: MASKED if keys.KEY_PREFIX.match(m.group(0)) or keys._random(m.group(0))
                  else m.group(0), text)


def rows(db: Path, sql: str, args=()) -> list:
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""


def setup_part(home: Path) -> list[str]:
    got = rows(home / "data" / "assistant.db", "select value_json from settings where key='setup'")
    if not got:
        return []
    s = json.loads(got[0][0])
    out = ["## Setup", "", f"- finished: {s.get('done')}", f"- steps: {s.get('steps')}", f"- failures: {s.get('fails')}",
           "- the setup thread keeps its last 200 lines", ""]
    for m in s.get("thread", []):
        if m["role"] == "log":
            out += [f"`{mask(m.get('text', ''))}`", ""]
            continue
        who = "Odie (a note to itself)" if m.get("note") else ("User" if m["role"] == "user" else "Odie")
        out += [f"**{who}:** {mask(m.get('text', ''))}", ""]
    return out


def part(p: dict) -> str | None:
    if p.get("text") and not p.get("thought"):
        return mask(p["text"])
    if fc := p.get("function_call"):
        return f"`→ {fc.get('name')}({mask(json.dumps(fc.get('args') or {}, ensure_ascii=False))[:600]})`"
    if fr := p.get("function_response"):
        return f"`← {fr.get('name')}: {mask(json.dumps(fr.get('response'), ensure_ascii=False))[:600]}`"
    return None


def chat_part(home: Path) -> list[str]:
    db = home / "data" / "sessions.db"
    out = []
    for (sid,) in rows(db, "select id from sessions order by create_time"):
        out += [f"## Chat thread {sid}", ""]
        for author, ts, data in rows(db, "select json_extract(event_data,'$.author'), timestamp, event_data from events "
                                         "where session_id=? order by timestamp", (sid,)):
            ev = json.loads(data)
            if ev.get("partial"):
                continue
            bits = [b for p in ((ev.get("content") or {}).get("parts") or []) if (b := part(p))]
            if bits:
                out += [f"**{'User' if author == 'user' else 'Odie'}** {when(ts)}: " + "\n\n".join(bits), ""]
    return out


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "~/.odie"
    home = Path(arg).expanduser()
    if not home.is_dir():
        home = Path("~/odie-runs").expanduser() / arg
    if not (home / "data").is_dir():
        sys.exit(f"No Odie home at {home}")
    lines = [f"# Conversations in {home}", "", f"Saved {datetime.now():%Y-%m-%d %H:%M}.", ""] + setup_part(home) + chat_part(home)
    dest = home / "logs" / "conversation.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")
    print(dest)


if __name__ == "__main__":
    main()
