"""The vault: logins in a keychain (a throwaway one here, never the login keychain), read back exactly, listed
without passwords, and the password never in a process's arguments."""
import json
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.signin import vault
from odie.store.db import Store

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def find(k, site, account):
    return subprocess.run(["security", "find-internet-password", "-s", site, "-a", account, "-w", str(k)], capture_output=True, text=True)


def test_save_read_and_list(store, keychain):
    vault.save(store, "https://www.amazon.in/ap/signin", "asha@example.com", "pw-123 secret", NOW)
    assert vault.get(store, "amazon.in") == ("asha@example.com", "pw-123 secret")
    listed = vault.listing(store)
    assert [(x["site"], x["username"]) for x in listed] == [("amazon.in", "asha@example.com")]
    assert listed[0]["saved_at"].startswith("2026-10-08") and listed[0]["last_used"] is None
    assert "pw-123" not in json.dumps(listed) and "pw-123" not in json.dumps(store.get_setting(vault.KEY))
    assert find(keychain, "amazon.in", "asha@example.com").stdout.startswith("b64:")  # base64 inside the item


@pytest.mark.parametrize("password", ["with space", 'dq"inside', "sq'inside", "back\\slash", "dollar $HOME", "tick `x`",
                                      "semi;amp&pipe|", "rupee ₹42", "ünïcödé ✓"])
def test_tricky_passwords_round_trip(store, keychain, password):
    vault.save(store, "amazon.in", "asha", password, NOW)
    assert vault.get(store, "amazon.in") == ("asha", password)


def test_the_password_never_appears_in_a_process_argument(store, keychain, monkeypatch):
    calls = []
    real = vault._security

    def spy(args, stdin=None):
        calls.append((list(args), stdin or ""))
        return real(args, stdin)
    monkeypatch.setattr(vault, "_security", spy)
    vault.save(store, "amazon.in", "asha", "argv-must-not-show", NOW)
    assert vault.get(store, "amazon.in")[1] == "argv-must-not-show"
    assert calls and not any("argv-must-not-show" in " ".join(args) for args, _ in calls)
    assert any(stdin.startswith("add-internet-password") for _, stdin in calls)


def test_one_login_per_site(store, keychain):
    vault.save(store, "amazon.in", "asha", "first", NOW)
    vault.save(store, "amazon.in", "bob", "second", NOW)
    assert vault.get(store, "amazon.in") == ("bob", "second")
    assert find(keychain, "amazon.in", "asha").returncode != 0  # the replaced login left the Keychain too


def test_delete_and_forget_all(store, keychain):
    vault.save(store, "amazon.in", "asha", "a", NOW)
    vault.save(store, "airbnb.co.in", "asha", "b", NOW)
    assert vault.delete(store, "amazon.in") and not vault.delete(store, "amazon.in")
    assert vault.get(store, "amazon.in") is None and find(keychain, "amazon.in", "asha").returncode != 0
    assert vault.forget_all(store) == 1
    assert vault.listing(store) == [] and find(keychain, "airbnb.co.in", "asha").returncode != 0


def test_used_marks_the_time(store, keychain):
    vault.save(store, "amazon.in", "asha", "a", NOW)
    vault.used(store, "amazon.in", NOW.replace(hour=10))
    assert vault.listing(store)[0]["last_used"].startswith("2026-10-08T10")
    vault.used(store, "not-saved.example", NOW)  # a site with no login: nothing happens
    assert len(vault.listing(store)) == 1


def test_unreadable_is_an_error_never_a_deletion(store, keychain, monkeypatch):
    """A locked keychain answers like a missing item: Odie says it can't open the vault, and forgets nothing. (Simulated:
    really locking the test keychain made macOS ask the owner for its password on screen.)"""
    vault.save(store, "amazon.in", "asha", "a", NOW)
    monkeypatch.setattr(vault, "_read", lambda site, username: None)  # what a locked keychain answers
    with pytest.raises(vault.VaultError, match="couldn't open its vault"):
        vault.get(store, "amazon.in")
    assert [x["site"] for x in vault.listing(store)] == ["amazon.in"]


def test_a_missing_keychain_never_becomes_the_login_keychain(store, monkeypatch, tmp_path):
    """Found 2026-10-08: given a keychain file that doesn't exist, `security` quietly uses the login keychain instead
    (a test's fake login landed there). The vault refuses before calling `security` at all."""
    calls = []
    monkeypatch.setattr(vault, "_security", lambda args, stdin=None: calls.append(args))
    monkeypatch.setenv("ODIE_KEYCHAIN", str(tmp_path / "missing.keychain-db"))
    with pytest.raises(vault.VaultError):
        vault.save(store, "amazon.in", "asha", "a", NOW)
    store.set_setting(vault.KEY, {"amazon.in": {"username": "asha", "saved_at": "x", "last_used": None}})
    with pytest.raises(vault.VaultError):
        vault.get(store, "amazon.in")
    with pytest.raises(vault.VaultError):
        vault.delete(store, "amazon.in")
    assert vault.forget_all(store) == 1 and vault.listing(store) == []
    assert calls == []  # not one call: nothing can reach the login keychain


def test_a_login_needs_all_three(store, keychain):
    for site, user, pw in (("", "asha", "a"), ("amazon.in", " ", "a"), ("amazon.in", "asha", "")):
        with pytest.raises(ValueError):
            vault.save(store, site, user, pw, NOW)


def test_saving_again_replaces_the_password(store, keychain):
    """Found live: changing a saved password for the same username failed (updating a Keychain item in place needs a
    person's authorization, which a background service can't give). Saving replaces the item instead."""
    vault.save(store, "amazon.in", "asha", "old password", NOW)
    vault.save(store, "amazon.in", "asha", "new password", NOW)
    assert vault.get(store, "amazon.in") == ("asha", "new password")



@pytest.mark.parametrize("site,user", [("amazon.in", "asha\nadd-internet-password"), ("amazon.in", "asha\r"), ("amazon\n.in", "asha")])
def test_control_characters_are_refused(store, keychain, site, user):
    """From the review: a newline would split the `security -i` command, and the first half loses its keychain."""
    with pytest.raises(ValueError):
        vault.save(store, site, user, "pw", NOW)


def test_a_username_with_quotes_round_trips(store, keychain):
    vault.save(store, "amazon.in", 'as"h\\a b', "pw", NOW)
    assert vault.get(store, "amazon.in") == ('as"h\\a b', "pw")
