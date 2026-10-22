"""A made-up brand kit for the tests (odie.video.brand): a plain background, a lantern that glows through the timed
segment, three bookends in flat colours, and a short neutral chime as its "ting". Everything in it is invented for the
tests; chime_wav is also a sound anyone can reuse as a kit's ting.wav."""
import array
import json
import math
import wave
from pathlib import Path

BACKGROUND = "#2B6CB0"  # the kit's background
LANTERN = "#38A169"  # the character
HANDOFF = "#D53F8C"
ENDING = "#DD6B20"
CARD = "#805AD5"

SCRIPT = """// A test kit: a plain background, a lantern through the timed segment, three bookends in flat colours.
(function () {
  const colours = {handoff: "%(handoff)s", ending: "%(ending)s", card: "%(card)s"};
  let left = null;  // the segment clock, as the stage last gave it
  const seen = [];  // what the stage asked the lantern to draw, for the tests to read
  window.Brand = {
    palette: {background: "%(background)s", lantern: "%(lantern)s"},
    background: function (ctx, t, w, h) {
      ctx.fillStyle = "%(background)s";
      ctx.fillRect(0, 0, w, h);
    },
    bookend: function (name, ctx, t, w, h, vars) {
      ctx.fillStyle = colours[name];
      const grown = Math.min(1, t / 1.0);  // a bar that grows over the first second, then holds
      ctx.fillRect(w * 0.1, h * 0.4, w * 0.8 * grown, h * 0.2);
    },
    lantern: {
      timer: function (secondsLeft) {
        left = secondsLeft;
      },
      draw: function (ctx, t, w, h, info) {
        const bouncing = info.moves.some(function (move) { return move.name === "bounce"; });
        let y = h - info.safe.bottom - 140;
        if (bouncing) {
          y -= 60;
        }
        ctx.fillStyle = "%(lantern)s";
        ctx.beginPath();
        ctx.arc(w - 200, y, 100, 0, Math.PI * 2);
        ctx.fill();
        seen.push({t: t, left: left, moves: info.moves.map(function (move) { return move.name; })});
      },
    },
    seen: function () {
      return seen.slice();
    },
  };
})();
""" % {"handoff": HANDOFF, "ending": ENDING, "card": CARD, "background": BACKGROUND, "lantern": LANTERN}

MANIFEST = {
    "name": "Test channel",
    "api_doc": "Brand.palette: {background, lantern}, the kit's colours, to match your text to them.",
    "sounds": {"ting": "ting.wav"},
    "background": True,
    "character": "lantern",
    "moves": {"bounce": 0.6},
    "vars": {"intro": "one short spoken line that leads into the timed part"},
    "bookends": {
        "handoff": {"seconds": 1.5, "says": "intro"},
        "ending": {"seconds": 1.0, "sounds": [{"at": 0.2, "name": "ting"}]},
        "card": {"seconds": 1.5, "sounds": [{"at": 0.1, "name": "ting"}]},
    },
}

CHIME_RATE = 48_000
CHIME_SECONDS = 1.0
# A bell-like ting: a fundamental and two overtones, each dying away at its own rate (frequency in Hz, level, decay
# a second). C6 with its octave and twelfth.
CHIME_PARTIALS = ((1046.5, 1.0, 4.0), (2093.0, 0.5, 6.0), (3139.5, 0.25, 9.0))
CHIME_ATTACK = 0.004  # seconds of rise, so it doesn't click
CHIME_FADE = 0.05  # seconds of fade at the end, so it stops in silence
CHIME_PEAK = 0.7  # of full scale


def chime_samples() -> list[float]:
    """The chime as samples from -1 to 1: the partials summed, a short rise, a fade at the end, the peak at 0.7."""
    count = int(CHIME_RATE * CHIME_SECONDS)
    samples = []
    for n in range(count):
        t = n / CHIME_RATE
        value = sum(level * math.exp(-decay * t) * math.sin(2 * math.pi * hz * t) for hz, level, decay in CHIME_PARTIALS)
        rise = min(1.0, t / CHIME_ATTACK)
        fade = min(1.0, (CHIME_SECONDS - t) / CHIME_FADE)
        samples.append(value * rise * fade)
    loudest = max(abs(value) for value in samples)
    return [value * CHIME_PEAK / loudest for value in samples]


def chime_wav(path: Path) -> Path:
    """Writes a short neutral chime: 1 s, mono, 48 kHz, 16-bit. Made from numbers alone, so it is the same every
    time."""
    data = array.array("h", (round(value * 32767) for value in chime_samples()))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(CHIME_RATE)
        w.writeframes(data.tobytes())
    return path


def make_kit(skills: Path, skill: str = "test-channel", manifest: dict | None = None, script: str = SCRIPT) -> Path:
    """The test kit written into a skill's assets/brand folder under `skills`; returns that folder."""
    folder = skills / skill / "assets" / "brand"
    folder.mkdir(parents=True, exist_ok=True)
    (skills / skill / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: a test skill\n---\nTest.\n")
    (folder / "brand.json").write_text(json.dumps(manifest or MANIFEST, indent=2))
    (folder / "brand.js").write_text(script)
    chime_wav(folder / "ting.wav")
    return folder
