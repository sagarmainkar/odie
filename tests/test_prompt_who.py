import re
from datetime import datetime
from zoneinfo import ZoneInfo

from odie.agent.prompt import ALL_CAPS, Who, build_static_prompt, build_turn_context, rules_text

NOW = datetime(2026, 10, 1, 7, 45, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_minimal_install_gets_no_rules_for_missing_tools():
    text = build_static_prompt(NOW, None, "", gated=True, who=Who(user="Asha", caps=frozenset()))
    for word in ("life_admin", "gmail", "calendar_list_events", "SMS ledger", "search_notes", "Connect Google"):
        assert word not in text, word
    assert "task_update" in text and "web_search" in text and "run_shell" in text


def test_vault_only_install_sees_no_ledger_or_mail_tools():
    text = rules_text(Who(caps=frozenset({"vault"})), gated=True)
    for word in ("life_admin", "gmail", "SMS", "Connect Google", "calendar_list_events"):
        assert word not in text, word
    assert "search_notes" in text


def test_full_install_keeps_every_rule():
    text = rules_text(Who(caps=ALL_CAPS), gated=True)
    assert "search_notes" in text and "task_update" in text and "web_search" in text


def test_identity_without_a_name():
    first = build_static_prompt(NOW, None, "", who=Who()).splitlines()[0]
    assert first.startswith("You are Odie, a personal assistant.")
    assert "Point out anything the user might be missing" in first and "Learn the user's preferences" in first


def test_identity_with_a_name():
    assert build_static_prompt(NOW, None, "", who=Who(user="Asha")).startswith("You are Odie, Asha's personal assistant.")


def test_identity_is_the_owners_personality_with_both_names_filled_in():
    """The default personality (no SOUL.md): enthusiastic, visual and with emojis, the chosen assistant name and the
    user's name in place, and no he/she about the user."""
    from odie.agent.prompt import identity
    text = identity(Who(user="Asha", assistant="Iris"))
    assert text == ("You are Iris, Asha's personal assistant. Brief, warm, concrete, enthusiastic and visual. Two or three "
                    "short sentences unless asked for detail. Point out anything Asha might be missing, with energy. Use "
                    "emojis to keep it vibrant. Learn Asha's preferences and tune how you talk to them. Ask questions when "
                    "it helps, but don't pester.")
    assert "No emoji" not in text and "Odie" not in text
    assert not re.search(r"\b(he|his|him|she|her|hers)\b", identity(Who()) + text, re.IGNORECASE)


def test_images_rule_puts_the_fence_on_lines_of_its_own():
    """Gemma copied "```odie-images block: {…} then ```" onto one line, and the chat showed the JSON (11 Oct 2026)."""
    for caps in (ALL_CAPS, ALL_CAPS | {"browser"}):
        [line] = [x for x in rules_text(Who(caps=caps), gated=True).splitlines() if x.startswith("- Images:")]
        assert "write ```odie-images on its own line" in line and "then ``` on its own line" in line
        assert "block: {" not in line


def test_money_what_ifs_go_to_the_calculator():
    """Gemma did a home-loan EMI sum itself, got it wrong, and never loaded the visuals skill (11 Oct 2026). The
    calculator is now in the system prompt itself (odie.blocks.visuals_prompt)."""
    text = rules_text(Who(), gated=True)
    assert "EMI, loan, SIP or budget what-ifs" in text
    assert "What-ifs go in the calculator: the phone works the numbers out exactly, so don't do the sums yourself." in text
    assert "### calculator" in build_static_prompt(NOW, None, "", who=Who())


def test_soul_keeps_the_users_name():
    text = build_static_prompt(NOW, "You are Odie, dry wit.", "", who=Who(user="Asha"))
    assert text.startswith("You are Odie, dry wit.") and "The user's name is Asha." in text
    assert "The user's name is" not in build_static_prompt(NOW, "You are Odie, dry wit.", "", who=Who())


def test_currency_and_machine_in_the_rules():
    text = rules_text(Who(machine="Mac", currency="€"), gated=True)
    assert '"unit": "€"' in text and "run_shell runs a command on this Mac" in text


def test_rules_never_use_he_or_his():
    text = rules_text(Who(), gated=True) + rules_text(Who(), gated=False)
    assert not re.search(r"\b(he|his|him|himself)\b", text, re.I)


def test_turn_context_calendar_note_only_with_a_calendar():
    with_cal = build_turn_context(NOW, "", "", brief="Two things.", caps=ALL_CAPS)
    without = build_turn_context(NOW, "", "", brief="Two things.", caps=frozenset())
    assert "calendar_list_events" in with_cal and "calendar_list_events" not in without and "Two things." in without
