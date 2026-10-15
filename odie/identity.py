"""Which app and user name the chat history is stored under. An install that already has chats keeps what they use,
so none disappear; a new one uses Odie's own. ODIE_APP_NAME / ODIE_USER_ID override both."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_APP, DEFAULT_USER = "odie", "user"


def stored_identity(sessions_db: Path) -> tuple[str, str] | None:
    """(app_name, user_id) with the most sessions in an existing sessions.db, or None."""
    if not sessions_db.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{sessions_db}?mode=ro", uri=True)
        try:
            row = con.execute("select app_name, user_id, count(*) as n from sessions group by app_name, user_id "
                              "order by n desc limit 1").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return (row[0], row[1]) if row else None
