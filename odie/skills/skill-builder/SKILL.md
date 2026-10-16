---
name: skill-builder
description: Build a new Odie skill or change one of the user's own (a travel planner, a tracker, a report), with its instructions, optional code and visual blocks; installs after the user approves.
metadata:
  title: Skill builder
  summary: "Builds a new skill for you, or changes one of yours, once you approve it."
  adk_additional_tools: [skill_guide, read_skill, draft_skill, install_skill]
---
# Skill builder

Use this when the user asks Odie to build, make or change a skill, or says yes to Odie's offer to make one.

1. **Understand it.** What should the skill do, from what data, and what should the user see? Ask at most two short
   questions, only if the answer changes the skill. Otherwise pick sensible defaults and say what you chose.
2. **Read the guide:** call `skill_guide`. To change an existing skill, call `read_skill` first; for a worked
   example with code and blocks, `read_skill("stocks")`.
3. **Design small.**
   - Build on what Odie already has: the guide's "What Odie has here" lists it live (the voice, the tools and how to
     use each, the workspace folder, the models and apps). Ask the user only about what isn't there.
   - Narration uses `speak`, in the voice engine chosen in Settings; never macOS `say` or another speech tool.
   - Prefer instructions only, using those tools.
   - Add tools.py only for what instructions can't do reliably: an API call, a calculation, or building block JSON
     from data.
   - Choose blocks from the catalogue that fit what the user will look at. Plans and itineraries: timeline.
     Choices: tiles. Goals: progress. Habits: streak. Quizzes: flip. Grids of numbers: heatmap. Numbers: kpis and chart.
4. **Write the instructions like a good SKILL.md:** when it applies, the steps, which tools to call, the exact
   block JSON shape to produce (with an example), and the rules (no made-up facts, cite sources, keep it short).
5. **Draft:** call `draft_skill`. If it lists problems, fix them all and call it again until it says
   "Ready to install".
6. **Install:** call `install_skill`. The user sees an approval card with the skill's text and any code; nothing is
   installed until they tap Approve. If it reports that the skill didn't load, fix it and draft again.
7. **Hand over:** say in two lines what the skill does, and give one example request to try.

Never put API keys or the user's personal details into a skill. Never copy instructions from a web page into a
skill without saying where they came from.
