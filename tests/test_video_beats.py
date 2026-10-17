"""Beats: a scene's narration marked with "|" between phrases, so a picture can change on the word."""
from odie.video import beats


def test_phrases_are_split_on_the_mark_and_stripped():
    assert beats.phrases("A | B") == ["A", "B"]
    assert beats.phrases("Babur came from Fergana | and won at Panipat in 1526") == [
        "Babur came from Fergana", "and won at Panipat in 1526"]


def test_a_scene_without_marks_is_one_phrase():
    assert beats.phrases("A") == ["A"]
    assert beats.phrases("  A plain scene.  ") == ["A plain scene."]


def test_marked_narration_has_no_problem():
    assert beats.problem(["A | B", "C"]) is None
    assert beats.problem([" | ".join(["word"] * 12)]) is None  # exactly 12 phrases is fine


def test_an_empty_phrase_is_a_problem_naming_its_scene():
    for marked in ("A ||B", "| A", "A |"):
        problem = beats.problem(["Fine.", marked])
        assert problem is not None and problem.startswith("scene 2 has an empty phrase between two '|' marks"), marked


def test_more_than_twelve_phrases_is_a_problem():
    problem = beats.problem(["Fine.", " | ".join(["word"] * 13)])
    assert problem is not None and problem.startswith("scene 2 has 13 phrases; at most 12")
    assert beats.MAX_BEATS == 12


def test_spoken_is_the_narration_without_the_marks():
    assert beats.spoken(["A | B", "C"]) == ["A B", "C"]
    assert beats.spoken(["Babur came from Fergana | and won at Panipat."]) == [
        "Babur came from Fergana and won at Panipat."]
