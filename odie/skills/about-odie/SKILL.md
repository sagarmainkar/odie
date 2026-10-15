---
name: about-odie
description: What Odie can do and how it's set up right now (abilities, skills, connected apps, models, voice, trackers, schedules, visual blocks, using it on a phone) and how to add more. Use for "what can you do", "do you have a skill for X", "can you ...?", "how do I add ...", "use you on my phone", "pair a device".
metadata:
  title: About Odie
  summary: "What Odie can do, how it's set up right now, and how to add more."
  adk_additional_tools: [odie_features]
---
# About Odie

Call `odie_features` and answer from what it returns. It's read live, so it's the truth about this setup.

- **"What can you do?"** Give a short tour grouped by area: a few lines, plus a single example of what to ask for
  each. Don't paste the whole list.
- **"Do you have X?" or "Can you X?"** Say yes or no plainly, using the list. If no:
  - if a new skill could do it, offer to build one (skill-builder)
  - if it's something that changes over time, offer a tracker
  - if it needs an outside service, point to Settings > Connected apps or Providers
- **"How do I add ...?"** Use the "How to add more" lines.
- **"Use you on my phone", pairing a device, a code that doesn't work:** give the "Phone and other devices" steps in
  order, one or two at a time. Never invent other steps (restarting Tailscale or an app): if those steps don't work,
  say so and point to Settings > Devices.
- **Never claim an ability, skill or app that isn't in the list.**
