"""The podcast as one kind of thing Odie makes in the background (odie.making.jobs): its writing step is the podcast
writer (odie.making.podcast_writer), which turns the topic, length and brief into a title and a two-host script; its
making step speaks each turn in its host's voice, joins the turns into one WAV and saves it as the chat's podcast
player. Importing this module registers the kind as "podcast", with its jobs under <workspace>/podcasts/<slug>/ (its
job.json and brief.md; the audio is kept with Odie's media, like every player in the chat).

job.data carries "turns" ([(host, plain speech)], in order) from the writing step to the making step."""
import httpx

from odie import media, voice
from odie.making import jobs, podcast_writer
from odie.store.db import Store
from odie.video.narrate import NO_ANSWER, first_line

FOLDER = "podcasts"


def hosts_in_order(turns: list[tuple[str, str]]) -> list[str]:
    """The hosts as they first speak: [("Host A", …), ("Host B", …), ("Host A", …)] -> ["Host A", "Host B"]."""
    hosts = []
    for host, _speech in turns:
        if host not in hosts:
            hosts.append(host)
    return hosts


async def speak_podcast(store: Store, script_turns: list[tuple[str, str]], title: str,
                        transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Speak a parsed script (podcast_writer.parse_script's turns) into one WAV and save it as the podcast player;
    returns its full media description (waveform, hosts, and the transcript with each turn's start), which the chat
    shows under the message. The first host to speak gets the woman's voice and the second the man's, from the engine
    chosen in Settings (voice.podcast_voices). A voice that can't be reached or says no is a VoiceUnavailable in one
    line: "Odie's voice didn't answer (Settings → Voice): Connection refused"."""
    woman, man = voice.podcast_voices(store)
    first, second = hosts_in_order(script_turns)
    voice_of = {first: woman, second: man}

    parts = []
    for host, speech in script_turns:
        try:
            part = await voice.speak_wav(store, speech, voice=voice_of[host]["id"], transport=transport)
        except httpx.HTTPError as e:
            raise voice.VoiceUnavailable(NO_ANSWER + first_line(e)) from e
        parts.append(part)

    audio, starts = media.join_wavs(parts)
    hosts = []
    for host in (first, second):
        hosts.append({"name": host, "voice": voice_of[host]["label"], "group": voice_of[host]["group"]})
    transcript = []
    for (host, speech), start in zip(script_turns, starts, strict=True):
        transcript.append({"host": host, "text": speech, "start": start})
    meta = {**media.wav_info(audio), "hosts": hosts, "transcript": transcript}
    return media.save(audio, "podcast", "wav", "audio/wav", title, meta)


async def write(job: jobs.Job, turn, browser) -> None:
    """The writing step: the podcast writer's focused turn, then the title and the turns onto the job. A podcast
    never uses the browser."""
    written = await podcast_writer.write(job.topic, job.minutes, job.brief, turn)
    job.title = jobs.title_after_writing(written.title, job)
    job.data["turns"] = written.turns


async def make(job: jobs.Job, browser, transport) -> dict:
    """The making step: the turns spoken in the two voices; returns the podcast player's media for the message."""
    return await speak_podcast(jobs.hooks["store"], job.data["turns"], job.title, transport=transport)


# Errors whose words are written for the user: the voice isn't running, or didn't answer.
KNOWN_ERRORS = (voice.VoiceUnavailable,)
KIND = jobs.Kind(word="podcast", folder=FOLDER, write=write, make=make, known_errors=KNOWN_ERRORS)
jobs.KINDS["podcast"] = KIND
