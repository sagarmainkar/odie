"""Bots: named Worker templates (spike, Nov 2026). A bot is a Worker with a name, a role, its own instructions, its own
model, the powers it may use and a folder that outlives its jobs (its notes.md is its memory).

The design follows Grok's team of agents: one lead, the chief, takes a request, splits it among specialists, runs them
side by side, weighs what they say against each other and gives one answer. Here the chief is a bot too. It makes the
specialists it needs (make_bot) and asks them (ask_bots); the user changes any bot's model, prompt and powers in
Settings → Bots. A bot the user edited is theirs: the chief can use it but no longer change it.

What a bot may do is fixed by its powers, never by what it reads:
- web: web search and fetch
- files: write_file and read_file in its folder
- notes: search the user's notes and photos by meaning, read a note (odie.vault.tools); once it has, its web steps ask
- shell: the shell, with the pass's always-ask rules refused (as for every Worker)
- browser: Odie's browser, signed in where the user is; every step the chat would ask about waits for the user's tap,
  and a sign-in waits for the user in the live view (odie.workers.asks)
Only the chief has the team tools (make_bot, list_bots, ask_bots); a specialist can't ask others or make bots."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from odie.store.db import Store, now_iso

POWERS = ("web", "files", "notes", "shell", "browser")
CHIEF = "chief"
MAX_BOTS = 12  # the chief's team, the chief included
NAME = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
ROLE_MAX = 160
PROMPT_MAX = 4000

CHIEF_ROLE = "Leads the team: splits your request among the bots, runs them side by side, weighs what they say and " \
             "gives you one answer."
CHIEF_PROMPT = """You lead a small team of bots, the way a captain leads specialists.

1. Read the request. If it is small enough to answer well with a web search or two, do it yourself.
2. Otherwise split it into two to four parts that can run at the same time, each for a specialist: one finds facts \
and sources, one checks the reasoning and the numbers, one looks for what the others would miss (the contrarian), \
or whatever this request needs. Call list_bots and use the bots you have; make one with make_bot only when none fits. \
Keep the team small: reuse bots across requests.
3. Call ask_bots once with all the parts, so they run side by side. Each brief stands alone: the bot sees nothing \
but its brief.
4. Weigh the answers. Where they disagree, say so and decide, or ask the one bot again with the other's point.
5. Report one answer to the user: the result first, then in a line or two who found what and where they disagreed."""


# The team Odie starts with, beside the chief, like Grok's: one finds, one checks, one argues. Made once (a setting
# remembers it), so a bot the user deletes stays deleted. The chief adds others when a job needs them.
STARTERS = (
    ("researcher", "Finds current facts, prices and sources on the web, with dates.",
     "Search, then open the best sources and read them. Give numbers with where and when you found them. Say what "
     "you couldn't confirm.", ["web", "files"]),
    ("checker", "Checks the numbers, the logic and the sources of an answer.",
     "Redo the arithmetic, check each claim against a source you open yourself, and list what is wrong or "
     "unsupported. Agree plainly where it holds.", ["web", "files"]),
    ("contrarian", "Looks for what the obvious answer misses: other options, hidden costs, weak assumptions.",
     "Argue the other side honestly. Find the assumption that, if wrong, changes the answer, and test it.",
     ["web", "files"]),
)
STARTERS_MADE = "bots.starters_made"

# A bot's creature (Fable's design, 15 Nov): shape, colour and eyes, picked from its name when it is made and then
# kept, so it never changes. The circle is Odie's alone; the chief is always the violet hexagon.
LOOK_COLORS = ("#F27B5B", "#F2A541", "#3FB8A8", "#4FA8E8", "#A77BF0", "#8CC152", "#EE7F9A", "#7C8AA5")
LOOK_SHAPES = ("hex", "cloud", "squircle", "pent", "pill", "drop", "tri", "flower")
LOOK_EYES = ("round", "tall", "calm", "stern", "dots", "side")
CHIEF_LOOK = {"shape": "hex", "color": "#8B6CF6", "eyes": "round"}


def name_hash(name: str) -> int:
    """The same number the app's mockup used: h = h * 31 + each character, kept to 32 bits. "researcher" -> one number,
    always the same."""
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h


def look_for(name: str, colors_taken: set[str]) -> dict:
    """A new bot's creature. The chief -> the violet hexagon. Others: shape, colour and eyes from the name's hash; when
    the colour is already another bot's, the next free one in LOOK_COLORS, so a small team never has two alike (all
    taken -> the hashed one).
      "researcher", nothing taken -> {shape, color, eyes} from its hash;  the same with that colour taken -> the next"""
    if name == CHIEF:
        return dict(CHIEF_LOOK)
    h = name_hash(name)
    start = (h >> 4) % len(LOOK_COLORS)
    color = LOOK_COLORS[start]
    for step in range(len(LOOK_COLORS)):
        candidate = LOOK_COLORS[(start + step) % len(LOOK_COLORS)]
        if candidate not in colors_taken:
            color = candidate
            break
    return {"shape": LOOK_SHAPES[h % len(LOOK_SHAPES)], "color": color, "eyes": LOOK_EYES[(h >> 9) % len(LOOK_EYES)]}


def colors_in_use(store: Store) -> set[str]:
    out = set()
    for r in store.query("select look_json from bots where look_json is not null"):
        out.add(json.loads(r["look_json"]).get("color"))
    return out


def shuffle_look(store: Store, name: str, pick=None) -> dict | None:
    """A new creature for a bot ("Shuffle look" in its details): another shape, colour and eyes, the colour one no
    other bot wears when there is one. The chief keeps its violet hexagon. Unknown bot -> None. pick: a test's
    stand-in for random.choice."""
    import random
    choose = pick or random.choice
    bot = get(store, name)
    if bot is None:
        return None
    if bot.is_chief:
        return dict(CHIEF_LOOK)
    taken = colors_in_use(store) - {(bot.look or {}).get("color")}
    free = [c for c in LOOK_COLORS if c not in taken and c != (bot.look or {}).get("color")] or list(LOOK_COLORS)
    look = {"shape": choose(LOOK_SHAPES), "color": choose(free), "eyes": choose(LOOK_EYES)}
    store.execute("update bots set look_json=? where name=?", (json.dumps(look), name))
    return look


def ensure_looks(store: Store) -> None:
    """Bots made before looks existed get one now, once (start up)."""
    for r in store.query("select name from bots where look_json is null order by created_at"):
        look = look_for(r["name"], colors_in_use(store))
        store.execute("update bots set look_json=? where name=?", (json.dumps(look), r["name"]))


@dataclass
class Bot:
    """A bot as stored. model: {"provider", "model"} or None for the chat's model. powers: a subset of POWERS."""
    name: str
    role: str
    prompt: str
    model: dict | None = None
    powers: list[str] = field(default_factory=list)
    made_by: str = "user"
    edited_by_user: bool = False
    look: dict | None = None

    @property
    def is_chief(self) -> bool:
        return self.name == CHIEF

    def as_dict(self) -> dict:
        return {"name": self.name, "role": self.role, "prompt": self.prompt, "model": self.model,
                "powers": list(self.powers), "made_by": self.made_by, "edited_by_user": self.edited_by_user,
                "chief": self.is_chief, "look": self.look or look_for(self.name, set())}


def clean_name(name: str) -> str | None:
    """A bot's name as stored, or None when it can't be one: lower case, starts with a letter, letters, digits and
    dashes, 2 to 24 characters. "Researcher" -> "researcher"; " fact-checker " -> "fact-checker"; "@writer" ->
    "writer"; "x" -> None; "my bot" -> None."""
    tidy = (name or "").strip().lstrip("@").lower()
    if NAME.match(tidy):
        return tidy
    return None


def clean_powers(powers: list[str] | None) -> list[str]:
    """The powers kept, in POWERS order, anything unknown dropped: ["Browser", "web", "mail"] -> ["web", "browser"];
    ["notes", "web"] -> ["web", "notes"]."""
    asked = {str(p).strip().lower() for p in (powers or [])}
    return [p for p in POWERS if p in asked]


def clean_model(model: dict | None) -> dict | None:
    """A model pick as stored: {"provider", "model"} with both set, else None (the chat's model).
    {"provider": "ollama", "model": "lfm3:latest", "x": 1} -> {"provider": "ollama", "model": "lfm3:latest"};
    {"provider": "ollama"} -> None; None -> None."""
    if not isinstance(model, dict):
        return None
    provider = str(model.get("provider") or "").strip()
    name = str(model.get("model") or "").strip()
    if not provider or not name:
        return None
    return {"provider": provider, "model": name}


def _from_row(row) -> Bot:
    model = json.loads(row["model_json"]) if row["model_json"] else None
    look = json.loads(row["look_json"]) if "look_json" in row.keys() and row["look_json"] else None
    return Bot(row["name"], row["role"], row["prompt"], model, json.loads(row["powers_json"] or "[]"), row["made_by"],
               bool(row["edited_by_user"]), look)


def ensure_chief(store: Store) -> None:
    """The chief is always there (made on start when missing; never deleted). The user may change its prompt, model
    and powers like any bot's; a chief that exists is left as it is."""
    if get(store, CHIEF) is None:
        now = now_iso()
        store.execute("insert into bots(name,role,prompt,model_json,powers_json,made_by,created_at,updated_at) "
                      "values(?,?,?,?,?,?,?,?)", (CHIEF, CHIEF_ROLE, CHIEF_PROMPT, None, json.dumps(["web"]), "odie",
                                                  now, now))


def ensure_starters(store: Store) -> None:
    """Odie's first start with bots: add the starter team (researcher, checker, contrarian) beside the chief, once.
    A name already taken is skipped. Second start, or after the user deleted one -> nothing."""
    if store.get_setting(STARTERS_MADE):
        return
    for name, role, prompt, powers in STARTERS:
        if get(store, name) is None:
            make(store, name, role, prompt, powers, made_by="odie")
    store.set_setting(STARTERS_MADE, True)


def get(store: Store, name: str) -> Bot | None:
    row = store.one("select * from bots where name=?", (name,))
    return _from_row(row) if row else None


def all_bots(store: Store) -> list[Bot]:
    """Every bot, the chief first, then by name."""
    rows = store.query("select * from bots order by name = 'chief' desc, name")
    return [_from_row(r) for r in rows]


def make(store: Store, name: str, role: str, prompt: str, powers: list[str] | None, model: dict | None = None,
         made_by: str = "chief") -> Bot | str:
    """Add a bot. Returns the bot, or a line saying why not: a bad name, one that exists, or a full team."""
    tidy = clean_name(name)
    if tidy is None:
        return "A bot's name is one word: lower case letters, digits and dashes, 2 to 24 characters (\"researcher\")."
    if get(store, tidy) is not None:
        return f"There is already a bot called {tidy}: use it as it is (the user edits bots in Settings)."
    if len(all_bots(store)) >= MAX_BOTS:
        return f"The team is full ({MAX_BOTS} bots): reuse one, or ask the user to delete one in Settings → Bots."
    role_line = " ".join((role or "").split())[:ROLE_MAX]
    if not role_line:
        return "Give the bot a role: one line on what it is for."
    now = now_iso()
    picked = clean_model(model)
    look = look_for(tidy, colors_in_use(store))
    store.execute("insert into bots(name,role,prompt,model_json,powers_json,made_by,look_json,created_at,updated_at) "
                  "values(?,?,?,?,?,?,?,?,?)",
                  (tidy, role_line, (prompt or "").strip()[:PROMPT_MAX], json.dumps(picked) if picked else None,
                   json.dumps(clean_powers(powers)), made_by, json.dumps(look), now, now))
    return get(store, tidy)


def edit(store: Store, name: str, role: str | None = None, prompt: str | None = None, powers: list[str] | None = None,
         model: dict | None = None, model_given: bool = False) -> Bot | None:
    """The user's change from Settings: whatever is given is replaced, and the bot is marked as theirs (the chief no
    longer changes it). model_given says the model was sent (None then means "the chat's model"). Unknown -> None."""
    bot = get(store, name)
    if bot is None:
        return None
    if role is not None:
        bot.role = " ".join(role.split())[:ROLE_MAX] or bot.role
    if prompt is not None:
        bot.prompt = prompt.strip()[:PROMPT_MAX]
    if powers is not None:
        bot.powers = clean_powers(powers)
    if model_given:
        bot.model = clean_model(model)
    store.execute("update bots set role=?, prompt=?, powers_json=?, model_json=?, edited_by_user=1, updated_at=? "
                  "where name=?", (bot.role, bot.prompt, json.dumps(bot.powers),
                                   json.dumps(bot.model) if bot.model else None, now_iso(), bot.name))
    return get(store, bot.name)


def delete(store: Store, name: str) -> bool:
    """Remove a bot (its folder and its jobs' record stay). The chief can't be deleted: -> False; unknown -> False."""
    if name == CHIEF or get(store, name) is None:
        return False
    store.execute("delete from bots where name=?", (name,))
    store.execute("delete from bot_routines where bot=?", (name,))  # its routines stop; their conversations stay
    return True


def folder_of(name: str) -> Path:
    """A bot's own folder, kept across its jobs: <workspace>/bots/<name>/ (made now). Its notes.md is its memory."""
    from odie.agent.tools.files import workspace
    folder = workspace() / "bots" / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def line_for(bot: Bot) -> str:
    """One line for list_bots: "researcher · finds and checks sources · web, files · ollama/lfm3:latest"."""
    model = f"{bot.model['provider']}/{bot.model['model']}" if bot.model else "the chat's model"
    powers = ", ".join(bot.powers) or "no tools"
    return f"{bot.name} · {bot.role} · {powers} · {model}"
