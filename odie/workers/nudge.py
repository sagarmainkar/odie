"""A one-line reminder to hand a long job to a Worker, on messages that look like one (the drawing nudge's twin,
odie.agent.visual_nudge). Live on 4 Nov the chat delegated when the message said "in the background" and reached for
its own shell when it didn't; a soft hint was not enough for DeepSeek, so the line is firm. The start_job docstring sits
thousands of tokens up the prompt; a line right after the question points the model back. The model still decides.
Something to check again and again is a tracker's, not a Worker's (no reporters), so it gets no nudge."""
from __future__ import annotations

import re

NUDGE = "[This is a job for a Worker: call start_job now with a full brief and say it started. Don't use run_shell here for it.]"

# Messages that read like a real long job (security review, 18 Nov: the old pattern fired on "test my knowledge of
# capitals" or "fix my resume wording"; a missed job costs little, as start_job's own description still invites it):
#   code to write AND run ("write a script … and run it"), tests to run or fix ("run the tests in ~/work/app",
#   "test the parser and fix what breaks"), a check of this computer ("check this Mac's disk"), or an explicit
#   "in the background" / "take your time" / "background job".
_JOB_ASK = re.compile(
    r"\b(write|build|create|make|code)\b.{0,60}\b(script|program|cli|tool)\b.{0,60}\b(and|then)\s+(run|test|execute)\b|"
    r"\b(run|fix)\b.{0,20}\b(the|my|its|all)\s+(unit\s+)?tests?\b|"
    r"\btest\b.{0,40}\band\s+fix\b|"
    r"\b(check|measure|report on)\b.{0,30}\b(this|my|the)\s+(mac|computer|machine|system|laptop)('s)?\b.{0,30}"
    r"\b(disk|memory|ram|cpu|battery|processes|ports?|logs?|storage)\b|"
    r"\bin the background\b|\bbackground (job|task|worker)\b|\btake your time\b",
    re.IGNORECASE,
)
# What is not a job however it is worded: a question to answer, a file the chat makes itself, a reminder, something to
# check again and again (a tracker's).
_NOT_A_JOB = re.compile(
    r"^\s*(what|why|how come|when|who|where|which|is|are|does)\b.{0,80}\?\s*$|"  # "can you test…?" is a request
    r"\b(remind me|reminder|podcast|deck|slides|pdf|explainer video)\b|"
    r"\b(every|each) (\d+ )?(minutes?|hour|hours|day|morning|evening)\b|\bkeep (an eye|watch|track)\b",
    re.IGNORECASE,
)


def looks_like_a_job(text: str) -> bool:
    """Decides whether this message gets the nudge to hand the work to a Worker. Worked examples:
      "Write a Python script that prints the first 20 primes and run it"  -> True  (write … script … and run)
      "Can you test the new parser and fix what breaks?"                  -> True  (test … and fix)
      "Run the tests in ~/work/app and fix what fails"                    -> True  (run … the tests)
      "Check this Mac's disk and memory and tell me"                      -> True  (check this Mac's … disk)
      "Do this in the background: …", "Take your time: …"                 -> True  (said so)
      "test my knowledge of capitals", "check my memory of last week"     -> False (questions, not jobs)
      "Fix my resume wording", "Create a simple app idea list"            -> False (small asks the chat answers)
      "Can you write a python function that reverses a string?"           -> False (code to show, not to run)
      "How is the market today?"                                          -> False (a question)
      "What does this script do?"                                         -> False (a question, even naming a script)
      "Remind me to run the tests at 5"                                   -> False (a reminder)
      "Make me a deck about tides"                                        -> False (the deck skill)
      "ls ~/Downloads"                                                    -> False (one command)
      "Track the HN front page and report every hour"                     -> False (a tracker's: again and again)"""
    if _NOT_A_JOB.search(text):
        return False
    return bool(_JOB_ASK.search(text))
