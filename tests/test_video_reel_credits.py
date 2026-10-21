"""A one-minute video (a reel) ends on its blink, never on a credits card: the web pictures' credits go in the chat's
ready message as a line for the post's caption. Longer videos keep Odie's credits card. Reels draw with the kit and
use web pictures only when the topic needs a real one (the owner's word, 21 Oct 2026)."""
from pathlib import Path

from odie.making import jobs
from odie.video import kind

CREDITS = ["Photo by A on Unsplash", "Pexels, by B"]


def job(minutes=1, aspect="vertical", **data):
    return jobs.Job(kind="video", slug="ice", title="Why ice is slippery", session_id="chat-1", minutes=minutes,
                    folder=Path("/tmp/ice"), data={"aspect": aspect, **data})


def test_a_reel_keeps_its_credits_off_the_screen_and_for_the_caption():
    reel = job()
    assert kind.credits_on_screen(reel, CREDITS) == []
    assert reel.data["caption_credits"] == CREDITS


def test_a_longer_video_keeps_its_credits_card():
    explainer = job(minutes=3, aspect="landscape")
    assert kind.credits_on_screen(explainer, CREDITS) == CREDITS
    assert "caption_credits" not in explainer.data


def test_the_ready_message_gives_a_reels_credits_for_the_caption():
    assert kind.ready_text(job(caption_credits=CREDITS)) == ("The video about Why ice is slippery is ready.\n\n"
                                                             "For the caption: Photo by A on Unsplash · Pexels, by B")
    assert kind.ready_text(job()) == "The video about Why ice is slippery is ready."  # nothing borrowed, nothing to add
    assert kind.KIND.ready_text is kind.ready_text


def test_a_reel_uses_web_pictures_only_when_the_topic_needs_a_real_one():
    rules = (Path(kind.__file__).parent / "writer-minute.md").read_text()
    assert "only when the topic needs" in rules and "caption" in rules
