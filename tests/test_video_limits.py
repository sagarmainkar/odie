"""The narration's limits, checked before anything is drawn: beat problems among them."""
from odie.video import limits


def test_an_empty_phrase_reaches_the_narration_problem():
    assert limits.narration_problem(["Hi.", "A || B"]).startswith(
        "scene 2 has an empty phrase between two '|' marks")


def test_too_many_phrases_reach_the_narration_problem():
    assert limits.narration_problem([" | ".join(["word"] * 13)]).startswith("scene 1 has 13 phrases; at most 12")


def test_the_older_checks_come_first():
    # a scene with no words is told as before, even when another scene has a stray mark
    assert limits.narration_problem(["| A", "  "]) == (
        "There's no narration for scene 2: every scene needs words to speak.")


def test_marked_narration_passes():
    assert limits.narration_problem(["Babur came from Fergana | and won at Panipat in 1526.", "Then Akbar."]) is None


def test_the_marks_are_not_counted_as_words_of_speech():
    # 40 scenes of 21 words are 840 words, exactly 6 minutes of speech (allowed); their 400 '|' marks add none
    marked = " | ".join(["two words"] * 10 + ["one"])
    narration = [marked] * 40
    assert limits.narration_problem(narration) is None
