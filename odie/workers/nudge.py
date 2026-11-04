"""A one-line reminder to hand a long job to a Worker, on messages that look like one (the drawing nudge's twin,
odie.agent.visual_nudge). Live on 4 Nov the chat delegated when the message said "in the background" and reached for
its own shell when it didn't. The start_job docstring sits thousands of tokens up the prompt; a line right after the
question points the model back. The model still decides."""
from __future__ import annotations

import re

NUDGE = "[If this takes code to write and run, a test, more than one shell command, or repeated checks, hand it to a Worker with start_job and answer now.]"

# Messages that read like a job: code or a script to write, something to build, run, test, fix, debug or install, a
# check on the machine, a repeated check or report, or an explicit ask for the background.
_JOB_ASK = re.compile(
    r"\b(write|build|create|make|fix|debug|test|run|install|set up|setup|refactor|implement|port|migrate|benchmark|profile|"
    r"compile|scaffold)\b.{0,60}\b(script|code|program|function|class|module|package|test|tests|app|cli|tool|repo|"
    r"project|bug|pipeline|service|server|library|library)\b|"
    r"\b(script|program|unit tests?|test suite)\b.{0,40}\b(write|build|make|run|fix)\b|"
    r"\b(test|fix|debug)\s+(the|my|this|our|what|it)\b|"
    r"\b(every|each) (\d+ )?(minutes?|hour|hours|day|morning|evening)\b|\bkeep (an eye|watch|track)\b|\btrack\b.{0,40}\breport\b|"
    r"\bin the background\b|\bbackground (job|task|worker)\b|"
    r"\b(check|measure|report on)\b.{0,40}\b(disk|memory|ram|cpu|uptime|battery|load|logs?|processes|ports?|network)\b",
    re.IGNORECASE,
)
# What is not a job however it is worded: a question to answer, a file the chat makes itself, a reminder.
_NOT_A_JOB = re.compile(
    r"^\s*(what|why|how come|when|who|where|which|is|are|does)\b.{0,80}\?\s*$|"  # "can you test…?" is a request
    r"\b(remind me|reminder|podcast|deck|slides|pdf|explainer video)\b",
    re.IGNORECASE,
)


def looks_like_a_job(text: str) -> bool:
    """Decides whether this message gets the nudge to hand the work to a Worker. Worked examples:
      "Write a Python script that prints the first 20 primes and run it"  -> True  (write … script)
      "Can you test the new parser and fix what breaks?"                  -> True  (test …, fix …)
      "Check this Mac's disk and memory and tell me"                      -> True  (check … disk)
      "Track the HN front page and report every hour"                     -> True  (every hour; track … report)
      "Do this in the background: …"                                      -> True  (in the background)
      "How is the market today?"                                          -> False (a question)
      "What does this script do?"                                         -> False (a question, even naming a script)
      "Remind me to run the tests at 5"                                   -> False (a reminder)
      "Make me a deck about tides"                                        -> False (the deck skill)
      "ls ~/Downloads"                                                    -> False (one command)"""
    if _NOT_A_JOB.search(text):
        return False
    return bool(_JOB_ASK.search(text))
