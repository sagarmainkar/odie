"""The helpers every "make it in the background" chat tool shares (odie.making.chat): reading the model's arguments,
the checks with each kind's own words and limits, a folder per job, and the reply."""
import pytest

from odie.making import chat


def test_the_slug_falls_back_to_the_kinds_word():
    assert chat.slug_of("Speculative decoding", "podcast") == "speculative-decoding"
    assert chat.slug_of("!!!", "podcast") == "podcast"
    assert chat.slug_of("!!!", "video") == "video"


def test_a_free_folder_never_reuses_an_earlier_one(tmp_path):
    (tmp_path / "tides").mkdir()
    (tmp_path / "tides-2").mkdir()
    assert chat.free_folder(tmp_path, "tides") == tmp_path / "tides-3"
    assert chat.free_folder(tmp_path, "moon") == tmp_path / "moon"


def test_null_text_is_empty():
    assert chat.text_or_empty(None) == "" and chat.text_or_empty("Asha") == "Asha"


@pytest.mark.parametrize(("given", "meant"), [(None, 4), ("4", 4), (" 7 ", 7), (3, 3), ("four", "four")])
def test_minutes_as_given_uses_the_kinds_default(given, meant):
    assert chat.minutes_as_given(given, 4) == meant


def test_the_minutes_check_says_the_kinds_range_and_default():
    assert chat.minutes_problem(10, 1, 10, "podcast", 4) is None
    assert chat.minutes_problem(11, 1, 10, "podcast", 4) == (
        "minutes is the podcast's length in whole minutes, from 1 to 10 (the user's length, else 4), not 11.")
    assert "got the text 'four'" in chat.minutes_problem("four", 1, 10, "podcast", 4)
    assert chat.minutes_problem(True, 1, 10, "podcast", 4) is not None


def test_the_brief_check_names_the_kind():
    assert chat.brief_problem("x" * 6000, "deck") is None
    problem = chat.brief_problem("x" * 6001, "deck")
    assert "6,001" in problem and "6,000" in problem and "what the deck needs" in problem


def test_a_kind_can_allow_a_longer_brief():
    assert chat.brief_problem("x" * 20_000, "video", 20_000) is None
    problem = chat.brief_problem("x" * 20_001, "video", 20_000)
    assert "20,001" in problem and "at most 20,000" in problem and "what the video needs" in problem


def test_the_reply_carries_the_kinds_middle_part():
    assert chat.reply(1, 2, 4, "writing the script, then speaking it") == (
        "Making it now: about 2–4 minutes (writing the script, then speaking it). It'll appear in this chat, with a "
        "ping on the phone, as soon as it's ready. Tell the user that in one or two lines, and that they can keep "
        "chatting meanwhile.")
    assert chat.reply(3, 2, 4, "anything").startswith("It's number 3 in line, about 2–4 minutes after the one before.")


def test_the_reply_can_say_the_wait_in_its_own_words():
    """For a kind whose wait isn't a range of minutes (a user skill's own estimate): the words go in as they are."""
    assert chat.reply_in_words(1, "about a minute", "writing it").startswith("Making it now: about a minute (writing it).")
    assert chat.reply_in_words(2, "about a minute", "anything").startswith(
        "It's number 2 in line, about a minute after the one before.")
