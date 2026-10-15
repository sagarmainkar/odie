# The sample chat

One made-up conversation the app shows under Settings → "See a sample chat" (`#sample`): ten turns through real Odie on
the demo home (Maya's notes, memories, mail and calendar from `video/demo`; nobody in it is real), recorded with
`record.py` on DeepSeek V4.1 Flash and drawn by the chat's own Markdown and blocks. It shows what Odie can show: mail
as rows, a timetable, a stocks table with charts, a diagram, a flights comparison, a donut, a heat map, flashcards.

- `sample-chat.json`: the chat, in the replay format (`odie/chat_replay.py`), scored by the app's parsers.
- `sample-chat.md`: what each turn drew, at a glance.
- `record.py`: records it again (after a change to the blocks or the prompt). Needs the demo home:
  `uv run python video/demo/make_home.py --root ~/odie-sample`, then `uv run python evals/sample/record.py`.

Unlike `evals/chats/` (your own test chats, never committed), this folder ships with the repo.
