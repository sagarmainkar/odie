"""The setup conversation: one turn calls the chosen chat model with only the setup tools and a short prompt that
carries the checklist, runs its tool calls (at most ROUNDS rounds), and returns the reply, any cards (key forms) and the
checklist. A key typed into it is stopped here: it never reaches the model or the thread."""
from __future__ import annotations

import json
import re

from odie import persona, profile
from odie.agent.model import complete
from odie.brain_check import SAMPLING
from odie.models import resolve_selection
from odie.setup import keys, panels, state, tools

ROUNDS = 6
FAILS = 3
KEY_REPLY = ("That looks like a key, so I didn't read it. Paste it into the key form instead: it goes straight to the settings "
             "and never to me.")
APP_REPLY = ("That link has a key in it, so I didn't read it. Paste it into the form instead: it goes straight to the "
             "settings and never to me.")
OTHER_APP_REPLY = ("That link has a key in it, so I didn't read it. Add it in Settings → Connected apps instead: it goes "
                   "straight to the settings and never to me.")
_THINK = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|$)", re.S)
_CARD_FOR = {"openai": "openai", "openrouter": "openrouter", "anthropic": "anthropic", "gemini": "gemini", "tavily": "tavily", "brave": "brave"}


MODEL_LINES = 40  # the most recent lines of the thread the model sees


def public_state(store) -> dict:
    s = state.get(store)
    return {"done": state.is_done(store), "can_leave": state.can_leave(store), "steps": s["steps"], "current": state.current(s),
            "skipped": [k for k, v in s["steps"].items() if v == "skipped"],
            "thread": [m for m in s["thread"] if m["role"] != "log"]}


async def view(store, transport=None) -> dict:
    """The checklist and thread, plus the current step's panel (its question and controls)."""
    return {**public_state(store), "panel": await panels.panel(store, transport=transport)}


async def prompt_for(store, transport=None) -> str:
    s = state.get(store)
    name, user = persona.get(store)["name"], profile.get(store)["user_name"]
    checklist = ", ".join(f"{k}: {v}" for k, v in s["steps"].items() if k != "brain")
    p = await panels.panel(store, transport=transport)
    here = ""
    if p:
        choices = "; ".join(f"{c['id']} ({c['label']})" for c in p["choices"]) or "none"
        explain = " ".join(t for t in (p["explain"], p.get("note", "")) if t)  # the note: what the screen shows as steps
        here = (f"\nCurrent step: {p['step']}. Its question, already on the screen: {p['question']} {explain} "
                f"Its choices, shown as buttons: {choices}" + ("; or skip." if p["skip"] else "."))
    return (f"You are {name}, setting yourself up for {user or 'the user'} on their computer. The screen shows each step's "
            "question with its choices as buttons and a Skip button; the user may tap them or type. If they type an answer, "
            "save it with the step's tool. If they ask a question, answer it in one or two plain sentences, then point them "
            "back to the choices. Offer only the current step's choices. Never ask for a key or an app's link in the chat: "
            "call request_key (or connect_app for Zapier and Composio) and wait to be told it was saved. Never say a step is "
            "saved unless a tool result said so. Setup finishes by itself when every step is done or skipped. "
            f"Keep each reply to two short sentences.\nChecklist: {checklist}.{here or ' Every step is done.'}")


def _next_line(store, p: dict | None) -> str:
    """What Odie says next: the current step's question, or the summary once setup is done."""
    if p:
        return p["question"]
    return panels.summary(store) if state.is_done(store) else ""


def _log_line(name: str, args: dict, out: dict) -> str:
    said = out.get("error") or out.get("result") or ("a form is on the screen" if out.get("card") else "")
    return f"{name}({json.dumps(args, ensure_ascii=False)[:300]}) → {json.dumps(said, ensure_ascii=False)[:300]}"


async def turn(store, text: str, transport=None, note: bool = False, runner=None) -> dict:
    """One exchange. note: a line from Odie itself (a key was saved), never a key and never caught. runner: so what
    setup saves (a vault) is live at once."""
    found = None if note else keys.key_in(text)
    if found:
        reply, card = KEY_REPLY, None
        if found in ("app_link", "composio"):
            app = "composio" if found == "composio" else _app_of(text)
            reply, card = (APP_REPLY, await tools.connect_app(store, app)) if app else (OTHER_APP_REPLY, None)
        elif found in _CARD_FOR:
            card = await tools.request_key(store, _CARD_FOR[found])
        state.add_to_thread(store, "assistant", reply)  # the reply stays; the user's text, with its key, doesn't
        return {"reply": reply, "cards": [card["card"]] if card else [], "state": public_state(store),
                "panel": await panels.panel(store, transport=transport)}
    sel = resolve_selection(store, "chat")
    said = [m for m in state.get(store)["thread"] if m["role"] != "log"][-MODEL_LINES:]
    messages = [{"role": "system", "content": await prompt_for(store, transport=transport)},
                *({"role": m["role"], "content": m["text"]} for m in said),
                {"role": "user", "content": text}]
    cards, reply = [], ""
    for _ in range(ROUNDS):
        try:  # through litellm, like every call Odie makes (odie.agent.model.complete)
            got = await complete(sel, messages, tools=tools.DECLARATIONS, tool_choice="auto", timeout=120, transport=transport, **SAMPLING)
            msg = got.choices[0].message.model_dump()
        except Exception as e:  # noqa: BLE001 (litellm's errors: the provider down or refusing, an answer that isn't JSON)
            reply = f"I couldn't reach my brain ({sel.provider.name}: {type(e).__name__}). Try again, or pick another in the brain step."
            break
        calls = msg.get("tool_calls") or []
        if not calls:
            reply = _THINK.sub("", msg.get("content") or "").strip()
            break
        sent = [{"id": call.get("id") or f"call_{i}", "type": "function", "function": call.get("function") or {}}
                for i, call in enumerate(calls)]
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": sent})
        for call in sent:
            fn = call["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) else fn.get("arguments") or {}
            except ValueError:
                args = {"_bad": True}
            out = await tools.run(str(fn.get("name")), args if isinstance(args, dict) else {"_bad": True}, store, runner=runner)
            state.add_to_thread(store, "log", _log_line(str(fn.get("name")), args if isinstance(args, dict) else {}, out))
            if out.get("card"):
                cards.append(out["card"])
            step = tools.STEP_OF.get(str(fn.get("name")))
            if "error" in out and step in state.SKIPPABLE and state.get(store)["fails"].get(step, 0) >= FAILS:
                state.mark(store, step, "skipped")
                out = {**out, "note": "This step failed three times, so it's skipped for now: tell the user they can do it "
                                      "later in Settings, and move on to the next step."}
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(out)})
    p = await panels.panel(store, transport=transport)
    if not reply:
        reply = _next_line(store, p) or "What would you like to do?"
    state.add_to_thread(store, "user", text, note=note)
    state.add_to_thread(store, "assistant", reply)
    return {"reply": reply, "cards": cards, "state": public_state(store), "panel": p}


async def choose(store, step: str, choice: str, value=None, transport=None, runner=None) -> dict:
    """A choice made on the screen: saved by code (never the model), then Odie's next line, also written by code: the
    next step's question, or the summary when setup is done. A choice that didn't work comes back as "error", with
    nothing saved. ValueError: not a choice of that step."""
    try:
        line = await panels.apply(store, step, choice, value, runner=runner, transport=transport)
    except panels.ChoiceError as e:
        return {"reply": "", "cards": [], "error": str(e), "state": public_state(store),
                "panel": await panels.panel(store, step, transport=transport)}
    state.add_to_thread(store, "log", f"screen: {step} → {choice}")
    p = await panels.panel(store, transport=transport)
    reply = f"{'' if choice == 'skip' else '✓ '}{line}\n\n{_next_line(store, p)}".strip()
    state.add_to_thread(store, "assistant", reply)
    return {"reply": reply, "cards": [], "state": public_state(store), "panel": p}


def _app_of(text: str) -> str | None:
    """Zapier or Composio, from the first link in the text with a key in it."""
    from odie.plugins.presets import preset_of
    link = next((w for w in text.split() if keys.secret_link(w.strip(".,;:()[]{}<>'\""))), "")
    return preset_of(link.strip(".,;:()[]{}<>'\"")) if link else None


async def event(store, kind: str, provider: str = "", transport=None, runner=None) -> dict:
    """Something happened on the screen (setup opened, a key was saved, a step skipped): the conversation carries on
    from it. Only known kinds and names get through: this text skips the key catcher. ValueError otherwise."""
    if kind == "start":  # the assistant speaks first, once
        if state.get(store)["thread"]:
            return {"reply": "", "cards": [], "state": public_state(store), "panel": await panels.panel(store, transport=transport)}
        p = await panels.panel(store, transport=transport)
        hello = ("Let's do the steps that are left. Everything else stays as it is." if state.can_leave(store) else
                 f"Hi! I'm {persona.get(store)['name']}. A few quick questions to set me up: tap an answer, or type if "
                 "you'd rather ask me something.")
        reply = f"{hello}\n\n{_next_line(store, p)}".strip()
        state.add_to_thread(store, "assistant", reply)
        return {"reply": reply, "cards": [], "state": public_state(store), "panel": p}
    if kind == "key_saved":
        if provider not in tools.KEYS:
            raise ValueError("unknown provider")
        kind_of, label, _ = tools.KEYS[provider]
        if kind_of == "search":
            state.mark(store, "search", "done")
        return await turn(store, f"(The {label} key was saved.)", transport=transport, note=True, runner=runner)
    if kind == "app_saved":
        from odie.plugins.presets import PRESETS
        if provider not in PRESETS:
            raise ValueError("unknown app")
        state.mark(store, "apps", "done")
        return await turn(store, f"(The {PRESETS[provider]['title']} connection was saved.)", transport=transport, note=True, runner=runner)
    if kind == "skipped":
        if provider not in state.SKIPPABLE:
            raise ValueError("that step can't be skipped")
        state.mark(store, provider, "skipped")
        return await turn(store, f"(The user skipped {provider} for now.)", transport=transport, note=True, runner=runner)
    raise ValueError("unknown event")
