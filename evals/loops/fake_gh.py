"""A stand-in for the GitHub CLI in tests and evals: it never reaches GitHub. It answers from the JSON file in
FAKE_GH_DATA and appends each call's arguments to FAKE_GH_LOG, one JSON list per line. What it knows:
  "user": "asha-dev"                          gh api user --jq .login
  "pr:example/app#49": {...}                  gh pr view 49 --repo example/app --json …
  "issue:example/app#7": {...}                gh issue view 7 --repo example/app --json …
  "diff:example/app#49": "diff --git …"       gh pr diff 49 --repo example/app
  "contents:example/app": ["pyproject.toml"]  gh api repos/example/app/contents --jq .[].name
  "clone:example/app": "/tmp/…/app-origin"    gh repo clone example/app <folder> -- …  (a local git repo, cloned)
  "collaborators:example/app": ["asha-dev"]   gh api repos/example/app/collaborators … (the logins with push)
  "keys:example/app": ["ci-deploy"]           gh api repos/example/app/keys … (deploy keys that can write; "error")
  "commits:example/app#49": [{sha, verified, login}]  gh api repos/example/app/pulls/49/commits …
  "prs:example/app@ledger": [{number, headRefOid, state, isCrossRepository}]  gh pr list --repo … --head ledger …
gh pr merge <n> --repo <r> --squash --match-head-commit <sha> merges only when <sha> is the pull request's
headRefOid; it then marks it MERGED in the data file, as GitHub would."""
import json
import os
import subprocess
import sys

args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
data_file = os.environ["FAKE_GH_DATA"]
data = json.loads(open(data_file).read())


def value_after(flag):
    return args[args.index(flag) + 1]


if args[:2] == ["api", "user"]:
    print(data.get("user", ""))
    sys.exit(0)
if args[:1] == ["api"] and len(args) > 1 and args[1].startswith("repos/") and args[1].endswith("/collaborators"):
    repo = args[1][len("repos/"):-len("/collaborators")]
    if f"collaborators:{repo}" not in data:
        print("HTTP 403: Must have push access to view repository collaborators.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(data[f"collaborators:{repo}"]))  # what the --jq filter gives: the logins with push
    sys.exit(0)
if args[:1] == ["api"] and len(args) > 1 and args[1].startswith("repos/") and args[1].endswith("/keys"):
    repo = args[1][len("repos/"):-len("/keys")]
    keys = data.get(f"keys:{repo}", [])
    if keys == "error":
        print("HTTP 404: Not Found", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(keys))  # the --jq filter's answer: titles of the keys that can write
    sys.exit(0)
if args[:1] == ["api"] and len(args) > 1 and args[1].startswith("repos/") and "/pulls/" in args[1] and args[1].endswith("/commits"):
    key = args[1][len("repos/"):-len("/commits")].replace("/pulls/", "#")
    print(json.dumps(data.get(f"commits:{key}", [])))  # [{sha, verified, login}]
    sys.exit(0)
if args[:1] == ["api"] and len(args) > 1 and args[1].startswith("repos/") and args[1].endswith("/contents"):
    repo = args[1][len("repos/"):-len("/contents")]
    for name in data.get(f"contents:{repo}", []):
        print(name)
    sys.exit(0)
if args[:2] == ["repo", "clone"]:
    origin = data.get(f"clone:{args[2]}")
    if not origin:
        print(f"GraphQL: Could not resolve to a Repository ({args[2]})", file=sys.stderr)
        sys.exit(1)
    done = subprocess.run(["git", "clone", "-q", origin, args[3]], capture_output=True, text=True)
    sys.stderr.write(done.stderr)
    sys.exit(done.returncode)
if args[:2] == ["pr", "list"]:  # gh pr list --repo R --head B …: the list under "prs:R@B" ("error": gh fails)
    prs = data.get(f"prs:{value_after('--repo')}@{value_after('--head')}", [])
    if prs == "error":
        print("HTTP 502: Bad Gateway", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(prs))
    sys.exit(0)
kind = {"pr": "pr", "issue": "issue"}.get(args[0])
if kind is None or "--repo" not in args or len(args) < 3:
    print("unknown command", file=sys.stderr)
    sys.exit(2)
key = f"{kind}:{value_after('--repo')}#{args[2]}"
if args[1] == "diff":
    print(data.get(f"diff:{value_after('--repo')}#{args[2]}", ""))
    sys.exit(0)
if key not in data:
    print(f"GraphQL: Could not resolve to a PullRequest ({key})", file=sys.stderr)
    sys.exit(1)
if args[1] == "merge":
    pr = data[key]
    if "--match-head-commit" not in args or value_after("--match-head-commit") != pr.get("headRefOid"):
        print("GraphQL: Head branch was modified. Review and try the merge again.", file=sys.stderr)
        sys.exit(1)
    pr["state"] = "MERGED"
    pr["mergedAt"] = "2026-11-18T15:34:00Z"
    with open(data_file, "w") as f:
        f.write(json.dumps(data))
    sys.exit(0)
if args[1] != "view":
    print("unknown command", file=sys.stderr)
    sys.exit(2)
print(json.dumps(data[key]))
