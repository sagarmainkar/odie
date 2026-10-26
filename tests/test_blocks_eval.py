"""The blocks eval's own pieces (odie/blocks_eval.py): the throwaway home, the one key it copies, file names, the grid.
The live run itself is scripts/blocks_eval.sh; the reply scorer is web/src/blocks/eval/score.ts (with its own tests)."""
import json
import os
from pathlib import Path

from odie import blocks_eval as be


def test_throwaway_env_points_every_folder_inside_the_root(tmp_path):
    env = be.throwaway_env(tmp_path)
    for name in ("ODIE_HOME", "ODIE_DATA_DIR", "ODIE_CONFIG_DIR", "ODIE_MEMORY_FILE", "ODIE_KEYCHAIN"):
        assert be.is_inside(env[name], tmp_path), name
        assert ".odie" not in env[name]
    assert env["ODIE_ADDONS"] == ""  # no mail or money add-ons
    assert env["ODIE_TRACE"] == "0"


def test_is_inside():
    assert be.is_inside("/tmp/x/home/data", Path("/tmp/x"))
    assert not be.is_inside(str(Path.home() / ".odie"), Path("/tmp/x"))


def test_copy_key_takes_only_the_named_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-test-123\nOTHER_KEY=nope\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OTHER_KEY", raising=False)
    assert be.copy_key("ANTHROPIC_API_KEY", env_file) is True
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test-123"
    assert "OTHER_KEY" not in os.environ
    assert be.copy_key("MISSING_KEY", env_file) is False


def test_key_name_for():
    assert be.key_name_for("anthropic") == "ANTHROPIC_API_KEY"
    assert be.key_name_for("ollama") is None  # on this computer, no key


def test_file_stem():
    assert be.file_stem("2026-10-11", "ollama", "glm-5.3-flash:cloud") == "2026-10-11-ollama-glm-5-3-flash-cloud"


def test_questions_are_unique_with_three_plain_ones():
    ids = [q.id for q in be.QUESTIONS]
    assert len(ids) == len(set(ids)) == 14
    assert [q.id for q in be.QUESTIONS if not q.expect] == ["capital", "thanks", "recursion"]


def test_two_questions_ask_for_a_form():
    """The model should answer these with a form: it needs several answers at once before it can help."""
    forms = [q for q in be.QUESTIONS if q.expect == [["form"]]]
    assert [q.id for q in forms] == ["weekend-trip", "story-video"]
    assert "ask me what you need to know first" in forms[0].ask and "ask me the choices" in forms[1].ask


def test_cell_for():
    assert be.cell_for({"verdict": "pass", "reasons": []}) == "✓"
    assert be.cell_for({"verdict": "fail", "reasons": ["no callout", "1 item dropped"]}) == "✗ no callout"
    assert be.cell_for({"verdict": "partial", "reasons": ["2 items dropped"]}) == "~ 2 items dropped"
    assert be.cell_for(None) == "–"


def _run(model: str, date: str, verdict: str = "pass") -> dict:
    q = {"id": "phones", "about": "3 phones (table)", "seconds": 10.0, "tokens": {"input": 5000, "output": 300},
         "score": {"verdict": verdict, "reasons": [] if verdict == "pass" else ["no blocks fence"]}}
    summary = {"pass": int(verdict == "pass"), "partial": 0, "fail": int(verdict == "fail"), "total": 1}
    return {"provider": "ollama", "model": model, "date": date, "questions": [q], "summary": summary}


def test_grid_markdown_has_a_column_per_model():
    grid = be.grid_markdown([_run("glm", "2026-10-11"), _run("kimi", "2026-10-11", "fail")])
    lines = grid.splitlines()
    assert lines[0] == "| Question | `ollama/glm` | `ollama/kimi` |"
    assert lines[2] == "| 3 phones (table) | ✓ | ✗ no blocks fence |"
    assert "1 ✓ · 0 ~ · 0 ✗ of 1" in grid


def test_latest_runs_keeps_the_newest_file_per_model(tmp_path):
    (tmp_path / "2026-10-01-ollama-glm.json").write_text(json.dumps(_run("glm", "2026-10-01", "fail")))
    (tmp_path / "2026-10-11-ollama-glm.json").write_text(json.dumps(_run("glm", "2026-10-11")))
    runs = be.latest_runs(tmp_path)
    assert [r["date"] for r in runs] == ["2026-10-11"]


def test_with_grid_replaces_only_the_marked_part():
    old = f"# Title\n\nIntro\n\n{be.GRID_START}\nold grid\n{be.GRID_END}\n\n## Analysis\nkept"
    new = be.with_grid(old, "new grid")
    assert new == f"# Title\n\nIntro\n\n{be.GRID_START}\nnew grid\n{be.GRID_END}\n\n## Analysis\nkept"
    fresh = be.with_grid("", "g")
    assert fresh.startswith("# Blocks eval") and f"{be.GRID_START}\ng\n{be.GRID_END}" in fresh


def test_reply_from_puts_each_piece_on_its_own_lines():
    pieces = ["Here's a list:", "```odie-blocks\n[]\n```\n", "  "]
    assert be.reply_from(pieces) == "Here's a list:\n\n```odie-blocks\n[]\n```"
    assert be.reply_from([]) == ""


def test_merged_run_replaces_only_the_questions_asked_again():
    saved = {"provider": "ollama", "model": "glm", "date": "2026-10-11", "odie_commit": "a",
             "questions": [{"id": "phones", "reply": "old"}, {"id": "kyoto", "reply": "old"}, {"id": "capital", "reply": "old"}]}
    fresh = {"provider": "ollama", "model": "glm", "date": "2026-10-12", "odie_commit": "b",
             "questions": [{"id": "kyoto", "reply": "new"}]}
    merged = be.merged_run(saved, fresh)
    assert [(q["id"], q["reply"]) for q in merged["questions"]] == [("phones", "old"), ("kyoto", "new"), ("capital", "old")]
    assert (merged["date"], merged["odie_commit"]) == ("2026-10-12", "b")
