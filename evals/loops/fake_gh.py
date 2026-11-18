"""A stand-in for the GitHub CLI in tests: it never reaches GitHub. It answers from the JSON file in FAKE_GH_DATA
({"pr:example/app#49": {...}, "issue:example/app#7": {...}, "user": "asha-dev"}) and appends each call's arguments to
FAKE_GH_LOG, one JSON list per line."""
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
data = json.loads(open(os.environ["FAKE_GH_DATA"]).read())
if args[:2] == ["api", "user"]:
    print(data.get("user", ""))
    sys.exit(0)
kind = {"pr": "pr", "issue": "issue"}.get(args[0])
if kind is None or args[1] != "view" or "--repo" not in args:
    print("unknown command", file=sys.stderr)
    sys.exit(2)
key = f"{kind}:{args[args.index('--repo') + 1]}#{args[2]}"
if key not in data:
    print(f"GraphQL: Could not resolve to a PullRequest ({key})", file=sys.stderr)
    sys.exit(1)
print(json.dumps(data[key]))
