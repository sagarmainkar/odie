# Odie: notes for anyone writing code here

## Writing code a human can follow

The owner reads and maintains this code. Write it so a person can follow it on the first read.

- Prefer a few plain named lines over one clever line. No nested `getattr(getattr(...))` (use
  `odie.agent.context.session_id_of` / `parts_of`, or two named lines), no conditional values packed into a call's
  arguments, no stacked `x or y or "..."` fallbacks where a named step reads better, no walrus tricks in conditions.
- Every decision function (predicates, guards, checks, `needs_tap`, `for_*`, `is_*` / `should_*`) gets a comment that
  says in words what it decides, with a concrete worked example: input -> outcome. For example, the shell pass:
  "`ls ~/Downloads` with a pass -> runs, no card; `rm old.txt` with a pass -> card anyway".
