"""Recall reads past chats' words out of a temp copy of ADK's session store (never the real one)."""
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from odie.app.runner import CHECK_PREFIX
from odie.recall.chats import ChatLine, chat_lines, exchanges

APP = "odie"
USER = "asha"
UTC_TZ = ZoneInfo("UTC")


def at(day: int, hour: int = 10, month: int = 11) -> float:
    return datetime(2026, month, day, hour, tzinfo=UTC).timestamp()


def make_db(path: Path, events: list[tuple[str, float, str, list[dict]]]) -> None:
    """events: (session_id, timestamp, author, parts). Each session gets a row in `sessions`."""
    db = sqlite3.connect(path)
    db.execute("create table sessions(id text, app_name text, user_id text, update_time real)")
    db.execute("create table events(session_id text, app_name text, user_id text, timestamp real, event_data text)")
    for sid in {e[0] for e in events}:
        db.execute("insert into sessions values (?,?,?,?)", (sid, APP, USER, 0.0))
    for sid, ts, author, parts in events:
        data = json.dumps({"author": author, "content": {"parts": parts}})
        db.execute("insert into events values (?,?,?,?,?)", (sid, APP, USER, ts, data))
    db.commit()
    db.close()


def say(sid: str, ts: float, author: str, text: str) -> tuple[str, float, str, list[dict]]:
    return (sid, ts, author, [{"text": text}])


def test_lines_keep_words_only(tmp_path):
    db_path = tmp_path / "sessions.db"
    assert db_path.parent == tmp_path
    sid = "chat-2026-11-03"
    make_db(db_path, [
        say(sid, at(3, 9), "user", "What is in the studio.local plan?\n\n[context: it is 9am]"),
        (sid, at(3, 10), "odie", [{"function_call": {"name": "search", "args": {}}}]),
        say(sid, at(3, 11), "odie", "(New chat.)"),
        say(sid, at(3, 12), "user", CHECK_PREFIX + "did you forget something?"),
        say(sid, at(3, 13), "odie", "Asha wants a small studio."),
        say("not-a-chat-session", at(3, 14), "user", "I am not a chat"),
    ])
    lines = chat_lines(db_path, APP, USER, at(3, 0), at(4, 0), UTC_TZ)
    assert lines == [
        ChatLine(sid, at(3, 9), "2026-11-03", "you", "What is in the studio.local plan?"),
        ChatLine(sid, at(3, 13), "2026-11-03", "odie", "Asha wants a small studio."),
    ]


def test_a_session_that_spans_days_is_split_by_message_time(tmp_path):
    db_path = tmp_path / "sessions.db"
    sid = "chat-2026-10-30-5"
    make_db(db_path, [
        say(sid, at(3, 9), "user", "Chapter one?"),
        say(sid, at(3, 9) + 5, "odie", "Dev walks into the barn."),
        say(sid, at(4, 8), "user", "And chapter two?"),
        say(sid, at(4, 8) + 5, "odie", "The barn burns."),
    ])
    lines = chat_lines(db_path, APP, USER, at(1, 0), at(4, 0), UTC_TZ)
    assert [line.text for line in lines] == ["Chapter one?", "Dev walks into the barn."]
    assert {line.day for line in lines} == {"2026-11-03"}


def test_the_day_is_in_the_users_timezone(tmp_path):
    db_path = tmp_path / "sessions.db"
    sid = "chat-2026-11-03"
    late = datetime(2026, 11, 3, 20, 0, tzinfo=UTC).timestamp()  # 01:30 on 4 Nov in Kolkata
    make_db(db_path, [say(sid, late, "user", "Late one")])
    lines = chat_lines(db_path, APP, USER, 0, late + 1, ZoneInfo("Asia/Kolkata"))
    assert lines[0].day == "2026-11-04"


def test_exchanges_pair_a_question_with_its_replies():
    sid = "chat-2026-11-03"
    lines = [
        ChatLine(sid, 1.0, "2026-11-03", "you", "First?"),
        ChatLine(sid, 2.0, "2026-11-03", "odie", "Answer A."),
        ChatLine(sid, 3.0, "2026-11-03", "odie", "Answer B."),
        ChatLine(sid, 4.0, "2026-11-03", "you", "Second?"),
        ChatLine(sid, 5.0, "2026-11-03", "odie", "x" * 5000),
    ]
    result = exchanges(lines)
    assert len(result) == 2
    assert result[0].text == "you: First?\nOdie: Answer A.\nOdie: Answer B."
    assert result[0].ts == 1.0
    assert result[0].session_id == sid
    assert result[0].day == "2026-11-03"
    assert result[1].ts == 4.0
    assert len(result[1].text) == 2000
    assert result[1].text.startswith("you: Second?\nOdie: xxx")


def test_exchanges_keep_chats_apart():
    lines = [
        ChatLine("chat-a", 1.0, "2026-11-03", "you", "Q a"),
        ChatLine("chat-b", 2.0, "2026-11-03", "odie", "stray reply in b"),
        ChatLine("chat-b", 3.0, "2026-11-03", "you", "Q b"),
        ChatLine("chat-b", 4.0, "2026-11-03", "odie", "A b"),
    ]
    result = exchanges(lines)
    assert [e.text for e in result] == ["you: Q a", "you: Q b\nOdie: A b"]


def test_chat_lines_reads_read_only(tmp_path):
    db_path = tmp_path / "sessions.db"
    make_db(db_path, [say("chat-2026-11-03", at(3), "user", "Hello")])
    os.utime(db_path, (1_000_000, 1_000_000))
    before = db_path.stat().st_mtime
    chat_lines(db_path, APP, USER, 0, at(5), UTC_TZ)
    assert db_path.stat().st_mtime == before


def test_a_missing_db_gives_no_lines(tmp_path):
    assert chat_lines(tmp_path / "nope.db", APP, USER, 0, at(5), UTC_TZ) == []
