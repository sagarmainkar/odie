# Where these files come from

`pptx_create.py` and `docx_create.py` are unchanged copies of the deck and document builders from Hermes Agent's
`powerpoint` (version 1.1.0) and `docx` skills, by Nous Research. They are MIT licensed: `LICENSE` here is the licence file shipped in those skill folders (the same text in both).

Odie doesn't run them as scripts. `odie/skills/documents/build.py` turns the assistant's Markdown into their JSON
specs and calls their functions directly (`build_slide`, `apply_page`, `add_styles`, `add_block`).
