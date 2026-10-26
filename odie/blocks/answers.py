"""A form's answer, as the user's message carries it: a line people read ("Where: Hills · Pace: Easy"), then an
```odie-form-answer fence the model reads by field id (the app writes both: web/src/blocks/formAnswer.ts). Where the
server uses the user's words to look things up or shows them as a title or a snippet, the fence is noise."""
from __future__ import annotations

import re

_ANSWER_FENCE = re.compile(r"\n*```odie-form-answer\n.*?\n```", re.DOTALL)


def without_form_answers(text: str) -> str:
    """The user's message without its form-answer fences, so lookups and titles see only the line people read.
    "Where: Hills\\n\\n```odie-form-answer\\n{...}\\n```" -> "Where: Hills"; "Plain words." -> "Plain words.";
    any other fence (```odie-blocks) stays."""
    return _ANSWER_FENCE.sub("", text).strip()
