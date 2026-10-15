"""How inventive each kind of model call is, all in one place. Temperature: 0 gives the same words every time, higher
gives more varied ones (and, past about 1, more mistakes). Chat's is a setting, "Creativity" in Settings → Brain; every
other job's is fixed here. Claude takes none of these: its newer models set their own (odie.agent.model._claude and
odie.models.chat_completion drop them)."""
from __future__ import annotations

# ── Chat: the user's own turns ──
CHAT_TEMPERATURE_SETTING = "chat.temperature"  # where Settings → Brain → Creativity is saved
CHAT_TEMPERATURE_DEFAULT = 0.7  # lively but on topic: what chat used before it was a setting
CHAT_TEMPERATURE_MIN = 0.0
CHAT_TEMPERATURE_MAX = 1.2      # beyond this, local models start to ramble
CHAT_TEMPERATURE_STEP = 0.1
CHAT_TOP_P = 0.95               # fixed: only the most likely 95% of next words are ever considered

# ── Fixed jobs ──
BACKGROUND_TEMPERATURE = 0.3     # tracker and watch checks nobody watches (OdieRunner.background_turn): factual, steady
MEMORY_REVIEW_TEMPERATURE = 0.2  # deciding what to remember: the same conversation should give the same memories
BRIEF_TEMPERATURE = 0.6          # the morning brief: warm, but only the facts it was given
VOICE_SCRIPT_TEMPERATURE = 0.6   # rewriting a reply as a script to read aloud: some life, same meaning
CHECK_TEMPERATURE = CHAT_TEMPERATURE_DEFAULT  # the brain check and model check try a model as chat runs by default


def chat_temperature(store) -> float:
    """The Creativity setting, or the default when it's unset or not a number between the minimum and maximum."""
    saved = store.get_setting(CHAT_TEMPERATURE_SETTING)
    is_number = isinstance(saved, (int, float)) and not isinstance(saved, bool)
    if not is_number:
        return CHAT_TEMPERATURE_DEFAULT
    if saved < CHAT_TEMPERATURE_MIN or saved > CHAT_TEMPERATURE_MAX:
        return CHAT_TEMPERATURE_DEFAULT
    return float(saved)
