"""The dialogue path is an extension: a video without a script must be made exactly as before it existed. The writer's
instruction, its message and its submit tool are compared with files saved from the version tagged stable-before-cast;
the narration and the page are covered by the existing narrate and kit tests, which this work leaves as they were."""
from pathlib import Path

from odie.video import page, writer

GOLDEN = Path(__file__).parent / "golden_video"


def test_a_video_without_a_script_gets_the_writers_instruction_as_before():
    assert writer.instruction_for("landscape") == (GOLDEN / "instruction_landscape.txt").read_text()
    assert writer.instruction_for("vertical", 60) == (GOLDEN / "instruction_vertical_timed60.txt").read_text()


def test_a_video_without_a_script_gets_the_writers_message_and_tool_as_before():
    prompt = writer.prompt_for("Tides", 2, "For a curious beginner.", "Pictures:\n  img1  1200x800  landscape  a beach")
    assert prompt == (GOLDEN / "prompt.txt").read_text()
    submit = writer.submit_doc(None) + "\n" + repr(sorted(writer.submit_fields(None)))
    assert submit == (GOLDEN / "submit.txt").read_text()


def test_a_page_without_lines_has_no_line_timeline():
    html = page.assemble('<script>Video.scenes([{draw(t, s) {}}])</script>', {"starts": [0.0], "lengths": [2.0]})
    assert "<script>Video.lines(" not in html
