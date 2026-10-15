"""The four deck themes (spec part 2): one set of tokens each, shared by the HTML (and so the PDF) and the PowerPoint.
System fonts only, so both look the same on a Mac or Windows without embedding fonts. Text over a photo is always
white on a dark veil, whatever the theme, so it stays readable."""
from __future__ import annotations

from dataclasses import dataclass

SERIF = 'Georgia, "Times New Roman", serif'
SANS = '"Helvetica Neue", Helvetica, Arial, sans-serif'


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    bg: str          # the slide background (a gradient from bg to bg2)
    bg2: str
    paper: str       # cards that hold a photo
    ink: str         # text on the background
    muted: str
    accent: str
    card: str        # cards and tiles without a photo
    card_line: str
    card_ink: str    # text on paper
    card_muted: str
    veil_a: str      # over a photo: from veil_a (where the text is) to veil_b
    veil_b: str
    head_font: str
    body_font: str
    head_weight: int
    pptx_head: str
    pptx_body: str
    dark: bool


THEMES: dict[str, Theme] = {
    "editorial": Theme("editorial", "Editorial", "#0a1420", "#16324a", "#f7f4ee", "#ffffff", "#c3d0dc", "#d9a441",
                       "rgba(255,255,255,0.07)", "rgba(255,255,255,0.15)", "#0e1b2a", "#6b7a88",
                       "rgba(6,14,24,0.88)", "rgba(6,14,24,0.12)", SERIF, SANS, 700, "Georgia", "Arial", True),
    "minimal": Theme("minimal", "Minimal", "#ffffff", "#f3f5f8", "#ffffff", "#111827", "#5b6472", "#2563eb",
                     "#f6f7f9", "#e3e7ee", "#111827", "#6b7280",
                     "rgba(12,17,28,0.82)", "rgba(12,17,28,0.10)", SANS, SANS, 700, "Arial", "Arial", False),
    "warm": Theme("warm", "Warm", "#f7f0e6", "#ecdfcb", "#fffaf3", "#2b1d14", "#76624f", "#b5532d",
                  "#fffaf3", "#e3d3bd", "#2b1d14", "#8a7562",
                  "rgba(43,29,20,0.86)", "rgba(43,29,20,0.12)", SERIF, SANS, 700, "Georgia", "Arial", False),
    "bold": Theme("bold", "Bold", "#0f0f10", "#1d1d21", "#ffffff", "#ffffff", "#cfcfd6", "#ff5a36",
                  "rgba(255,255,255,0.07)", "rgba(255,255,255,0.16)", "#111111", "#6b6b73",
                  "rgba(0,0,0,0.86)", "rgba(0,0,0,0.10)", SANS, SANS, 800, "Arial Black", "Arial", True),
}


def theme(name: str | None) -> Theme:
    """The theme by name (any case); anything else is Editorial."""
    return THEMES.get((name or "").strip().lower(), THEMES["editorial"])
