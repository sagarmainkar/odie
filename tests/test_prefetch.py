"""Context prefetch: vault + SMS ledger searched before the reply, blocks kept on recent turns."""
from google.genai import types

from odie.agent import prefetch as pf
from odie.agent.compaction import compact, size_of


def test_skip_list():
    for t in ["thanks", "ok", "Got it!", "remind me at 6 to call mom", "mark the ICICI one done", "snooze it", "send it", "yes", "no thanks"]:
        assert not pf.should_search(t), t
    for t in ["What did I decide about the home server memory settings?", "How much did I spend on Amazon this week?",
              "When is the electricity bill due?"]:
        assert pf.should_search(t), t


def test_keywords_prefer_current_message_and_skip_filler():
    kws = pf.keywords("When is the ACME bill due?", ["what about my ICICI card", "thanks"])
    assert kws[0].lower() == "acme"
    assert "when" not in [k.lower() for k in kws] and "the" not in [k.lower() for k in kws]
    assert len(kws) <= pf.MAX_KEYWORDS


def test_query_joins_current_then_previous():
    q = pf.vault_query("and Thursday?", ["Am I free on Wednesday?", "What's on my calendar this week?"])
    assert q.startswith("and Thursday?") and "Wednesday" in q


def _user(text):
    return types.Content(role="user", parts=[types.Part(text=text)])


def _model(text):
    return types.Content(role="model", parts=[types.Part(text=text)])


def test_blocks_stay_as_sent_until_a_cut():
    """Prefetched blocks and [context: …] notes stay on every earlier message exactly as sent (so the provider reuses
    its cache), and come off the older part only when a cut sends it as words only (odie.agent.compaction)."""
    block = f"\n\n{pf.NOTES_OPEN}\nnote\n{pf.NOTES_CLOSE}"

    def convo(n):
        out = []
        for i in range(n):
            out += [_user(f"q{i}{block}\n\n[context: now]"), _model(f"a{i}")]
        return out

    def kept(contents):
        return [i for i, c in enumerate([c for c in contents if c.role == "user"]) if pf.NOTES_OPEN in c.parts[0].text]

    assert kept(compact(convo(12))) == list(range(12))  # under the limit: all as sent
    users = [c for c in compact(convo(12)) if c.role == "user"]
    assert all("[context: now]" in u.parts[0].text for u in users)
    full = convo(12)
    limit = sum(size_of(c) for c in full[:22]) - 1  # passed only at the last question: the cut lands there
    squeezed = [c for c in compact(full, limit=limit, keep=0) if c.role == "user"]
    assert kept(squeezed) == [11] and all(u.parts[0].text == f"q{i}" for i, u in enumerate(squeezed[:-1]))


def test_a_question_that_starts_with_ok_still_searches():
    from odie.agent.prefetch import should_search
    assert should_search("Ok great, I was looking to rewind myself on the Transformers and LLM concepts")
    assert should_search("Yes and what did I note about the Electricity meter?")
    assert not should_search("ok thanks a lot")        # a short acknowledgement
    assert not should_search("great, that works fine")
    assert not should_search("remind me to call the plumber about the kitchen tap tomorrow")  # commands: any length


def test_question_words_are_not_ledger_keywords():
    assert [k.lower() for k in pf.keywords("Anything in mail I should answer?", [])] == []

