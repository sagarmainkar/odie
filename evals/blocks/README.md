# Blocks eval: how well a model draws Odie's visual blocks

`scripts/blocks_eval.sh <provider>/<model>` asks 12 fixed questions through Odie's real runner (the real prompt, tools
and skills; a fresh chat each; a throwaway home with nothing from `~/.odie` but that provider's key). Each reply is
scored with the web app's own parser (`web/src/blocks/eval/score.ts`), so "dropped" means exactly what the phone would
drop. Results land in this folder, one `.json` and one `.md` per model, and the table below is redrawn. To see the
replies drawn: **#blocks → Eval** in the app.

✓ drew what the question wanted (or nothing, for a plain question) · ~ drew it but the parser dropped something ·
✗ didn't.
