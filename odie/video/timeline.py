"""When each scene starts and how many frames a video needs: the narration sets the lengths (voice first, then the
picture), with a short breath between scenes."""
import math

BREATH = 0.5            # seconds of quiet between scenes
FPS = 30                # set from Task 1's measurement
MAX_MINUTES = 6
WORDS_PER_MINUTE = 140
TABS = 4                # tabs that render frames at once (measured rate still rising at 4)
RENDER_RATE = 70        # frames drawn a second in total with 4 tabs (measured: 70 a second on the GPU)

# A video's stage in pixels, (width, height), by its aspect. Frames stay time-based (FPS x seconds) in both.
LANDSCAPE = (1920, 1080)
VERTICAL = (1080, 1920)  # a reel: Instagram, Shorts
SIZES = {"landscape": LANDSCAPE, "vertical": VERTICAL}
# On a reel, Instagram's own buttons and caption cover about the top 120 px and the bottom 320 px: the page gets this
# much room on each side as CSS variables (--safe-top, --safe-bottom, --safe-side) and as s.safe.
SAFE_VERTICAL = {"top": 140, "bottom": 340, "side": 72}


def size_of(aspect: str) -> tuple[int, int]:
    """A video's (width, height) from its aspect: "vertical" -> (1080, 1920); "landscape" -> (1920, 1080); "",
    "square" or any other word -> (1920, 1080), as every video before aspects."""
    return SIZES.get(aspect, LANDSCAPE)


def safe_area(size: tuple[int, int]) -> dict[str, int]:
    """The room a page keeps clear of a platform's buttons, in pixels: the vertical stage -> {"top": 140, "bottom":
    340, "side": 72}; the landscape stage -> all 0 (nothing covers a wide video)."""
    if size == VERTICAL:
        return dict(SAFE_VERTICAL)
    return {"top": 0, "bottom": 0, "side": 0}


def scene_starts(durations: list[float], breath: float = BREATH) -> tuple[list[float], float]:
    """Each scene's start and the video's length, from the scenes' narration lengths.
    [4.0, 2.5, 3.0] -> ([0.0, 4.5, 7.5], 10.5): scene 2 starts after scene 1's 4 s and a 0.5 s breath."""
    starts = []
    t = 0.0
    for i, length in enumerate(durations):
        if i:
            t += breath
        starts.append(round(t, 3))
        t += length
    return starts, round(t, 3)


def frame_count(total: float, fps: int = FPS) -> int:
    """Frames to draw: 10.5 s at 30 fps -> 315; 10.51 s -> 316 (the last partial frame is drawn too)."""
    return math.ceil(round(total * fps, 6))


def spoken_minutes(narration: list[str]) -> float:
    """Minutes of speech for the narration texts, at 140 words a minute: 210 words -> 1.5 minutes."""
    words = sum(len(text.split()) for text in narration)
    return round(words / WORDS_PER_MINUTE, 2)
