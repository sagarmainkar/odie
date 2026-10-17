"""Beats: the moments inside a scene where a picture changes on the word. The writer marks them in a scene's
narration with "|" between phrases ("Babur came from Fergana | and won at Panipat in 1526"); Odie speaks each phrase
on its own and the page learns, from the measured speech, the second at which each phrase starts. A scene without
marks is one phrase, so one beat."""

MARK = "|"
MAX_BEATS = 12  # the most phrases one scene may have


def phrases(text: str) -> list[str]:
    """The phrases of one scene's narration, split on "|" and stripped: "A | B" -> ["A", "B"]; "A" -> ["A"]; a stray
    mark leaves an empty phrase, "A |" -> ["A", ""] (problem() refuses it before anything is spoken)."""
    pieces = text.split(MARK)
    return [piece.strip() for piece in pieces]


def problem(narration: list[str]) -> str | None:
    """Decides whether every scene's marks make phrases that can be spoken: the first problem as words to act on, or
    None. ["Hi.", "A || B"] (or "| A", or "A |") -> scene 2 has an empty phrase; a scene of 13 phrases -> over the
    12-phrase limit; ["A | B", "C"] -> None."""
    for number, text in enumerate(narration, start=1):
        pieces = phrases(text)
        if "" in pieces:
            return (f"scene {number} has an empty phrase between two '{MARK}' marks: put words between every two "
                    f"marks, and no mark at the start or the end of a scene.")
        if len(pieces) > MAX_BEATS:
            return (f"scene {number} has {len(pieces)} phrases; at most {MAX_BEATS}. Remove some '{MARK}' marks, "
                    "keeping the ones where the picture must change on the word.")
    return None


def spoken(narration: list[str]) -> list[str]:
    """The narration as it is said, one text per scene without the marks: ["A | B", "C"] -> ["A B", "C"]."""
    texts = []
    for text in narration:
        words = [piece for piece in phrases(text) if piece]
        texts.append(" ".join(words))
    return texts
