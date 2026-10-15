"""Print a request Odie sent to the model, readably: settings, every message in order, and the tool list.

    scripts/last_prompt.sh          the newest request (the last model call of the last turn)
    scripts/last_prompt.sh 2        the second newest, and so on (a turn with tools makes several calls)
    scripts/last_prompt.sh --full   also print every tool schema
"""
import json
import os
import sys
from pathlib import Path

folder = Path(os.environ.get("ODIE_DATA_DIR", "~/.odie/data")).expanduser() / "requests"
args = [a for a in sys.argv[1:] if a != "--full"]
n = int(args[0]) if args else 1
files = sorted(folder.glob("*.json"))
if len(files) < n:
    sys.exit(f"Only {len(files)} saved request(s) in {folder}. Send Odie a message first.")
f = files[-n]
d = json.loads(f.read_text())
print(f"file: {f}")
print(f"model: {d.get('model')}   reasoning_effort: {d.get('reasoning_effort', '(not sent)')}   temperature: {d.get('temperature')}   stream: {d.get('stream')}")
tools = d.get("tools") or []
print(f"tools: {len(tools)} ({len(json.dumps(tools)):,} characters of schema)")
for i, m in enumerate(d.get("messages", [])):
    head = f"\n========== messages[{i}]  role: {m['role']}"
    if m.get("tool_calls"):
        head += "  calls: " + ", ".join(f"{c['function']['name']}({c['function']['arguments']})" for c in m["tool_calls"])
    if m.get("tool_call_id"):
        head += f"  answers call: {m['tool_call_id']}"
    print(head + " ==========")
    c = m.get("content")
    if isinstance(c, list):
        c = "\n".join(p.get("text") or json.dumps(p, ensure_ascii=False) for p in c)
    print(c if c else "(no text)")
print("\n========== tools ==========")
for t in tools:
    fn = t.get("function", {})
    if "--full" in sys.argv:
        print(json.dumps(t, indent=1, ensure_ascii=False))
    else:
        print(f"- {fn.get('name')}: {(fn.get('description') or '').splitlines()[0][:110]}")
