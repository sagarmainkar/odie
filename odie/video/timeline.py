"""When each scene starts and how many frames a video needs: the narration sets the lengths (voice first, then the
picture), with a short breath between scenes."""
import math

BREATH = 0.5            # seconds of quiet between scenes
FPS = 30                # set from Task 1's measurement
MAX_MINUTES = 6
WORDS_PER_MINUTE = 140
TABS = 4                # tabs that render frames at once (measured rate still rising at 4)
RENDER_RATE = 70        # frames drawn a second in total with 4 tabs (measured: 70 a second on the GPU)


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
