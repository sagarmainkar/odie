from odie.video import timeline


def test_scenes_follow_each_other_with_a_breath():
    starts, total = timeline.scene_starts([4.0, 2.5, 3.0])
    assert starts == [0.0, 4.5, 7.5] and total == 10.5


def test_one_scene_has_no_breath():
    assert timeline.scene_starts([3.2]) == ([0.0], 3.2)


def test_frames_cover_the_whole_length():
    assert timeline.frame_count(10.5, fps=30) == 315
    assert timeline.frame_count(10.51, fps=30) == 316  # a partial frame still gets drawn


def test_spoken_minutes_from_words():
    assert timeline.spoken_minutes(["word " * 140, "word " * 70]) == 1.5
