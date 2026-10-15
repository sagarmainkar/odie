"""Sign-in's core: the switch (off by default, on only with the box ticked and the current terms), the signed-in sites
(registrable domains), and the money patterns (refused in memory, masked on pages) with false-positive checks."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie.signin import money, sites, state
from odie.store.db import Store

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_the_switch_is_off_and_turns_on_only_with_the_box_ticked(store):
    assert state.get(store) == {"on": False, "accepted_at": None, "accepted_version": None, "terms_changed": False} and not state.is_on(store)
    with pytest.raises(ValueError, match="Tick"):
        state.turn_on(store, accepted=False, version=state.VERSION, now=NOW)
    with pytest.raises(ValueError, match="changed"):
        state.turn_on(store, accepted=True, version=state.VERSION - 1, now=NOW)
    got = state.turn_on(store, accepted=True, version=state.VERSION, now=NOW)
    assert got["on"] and got["accepted_version"] == state.VERSION and got["accepted_at"].startswith("2026-10-08")
    assert state.is_on(store) and "I understand and accept these risks" in state.DISCLAIMER


def test_turning_off_clears_the_list(store):
    state.turn_on(store, accepted=True, version=state.VERSION, now=NOW)
    sites.record(store, "amazon.in", NOW)
    assert state.turn_off(store)["on"] is False and sites.listing(store) == [] and not state.is_on(store)


@pytest.mark.parametrize("given,site", [
    ("https://www.amazon.in/gp/your-orders", "amazon.in"),
    ("pay.amazon.in", "amazon.in"),
    ("amazon.com", "amazon.com"),
    ("https://www.bbc.co.uk/news", "bbc.co.uk"),
    ("https://the-internet.herokuapp.com/secure", "the-internet.herokuapp.com"),  # shared hosting: anyone's app is a site
    ("https://evil.herokuapp.com/x", "evil.herokuapp.com"),
    ("https://someone.github.io/page", "someone.github.io"),
    ("https://shop-preview.vercel.app/", "shop-preview.vercel.app"),
    ("localhost", "localhost"),
    ("http://127.0.0.1:8011/x", "127.0.0.1"),
    ("", ""),
])
def test_site_of(given, site):
    assert sites.site_of(given) == site


def test_the_sites_list(store):
    sites.record(store, "amazon.in", NOW)
    sites.record(store, "airbnb.co.in", NOW + timedelta(minutes=5))
    assert [s["domain"] for s in sites.listing(store)] == ["airbnb.co.in", "amazon.in"]
    assert sites.is_signed_in(store, "https://pay.amazon.in/checkout") and not sites.is_signed_in(store, "https://amazon.com/")
    sites.touch(store, "amazon.in", NOW + timedelta(hours=1))
    assert next(s for s in sites.listing(store) if s["domain"] == "amazon.in")["last_used"].startswith("2026-10-08T10")
    assert sites.remove(store, "amazon.in") and not sites.remove(store, "amazon.in")
    assert not sites.is_signed_in(store, "https://www.amazon.in/")


@pytest.mark.parametrize("text,refused", [
    ("my card is 4111 1111 1111 1111", True),
    ("card 4111-1111-1111-1111 exp 12/28", True),
    ("CVV: 123", True),
    ("pay to ashaa@okaxis please", True),
    ("upi id asha.m@ybl", True),
    ("IFSC HDFC0001234", True),
    ("A/c 50100123456789", True),
    ("+91 98765 43210", False),
    ("order 402-7731234-1234567", False),
    ("2026-10-08 at 14:30", False),
    ("₹4,200 a night", False),
    ("flight 6E 2134", False),
    ("pin code 411001", False),
    ("asha@gmail.com", False),
    ("1234 5678 9012 3456", False),  # 16 digits that fail the Luhn check: not a card
])
def test_holds_financial(text, refused):
    assert (money.holds_financial(text) is not None) is refused


def test_mask():
    assert money.mask("Visa 4111 1111 1111 1111 saved") == "Visa •••• 1111 saved"
    assert money.mask("A/c no. 50100123456789, IFSC HDFC0001234") == "A/c no. ••••6789, IFSC HDFC0001234"
    assert money.mask("CVV 123") == "CVV •••"
    for plain in ("+91 98765 43210", "order 402-7731234-1234567", "₹4,200", "pin code 411001", "ashaa@okaxis"):
        assert money.mask(plain) == plain


def test_new_terms_ask_again(store):
    store.set_setting(state.KEY, {"on": True, "accepted_at": "2026-10-01T09:00:00+05:30", "accepted_version": state.VERSION - 1})
    got = state.get(store)
    assert not state.is_on(store) and got["on"] is False and got["terms_changed"] is True
    state.turn_on(store, accepted=True, version=state.VERSION, now=NOW)
    assert state.is_on(store) and state.get(store)["terms_changed"] is False


def test_a_site_remembers_where_it_was_seen(store):
    sites.record(store, "amazon.in", NOW, origins=["https://www.amazon.in", "https://pay.amazon.in", "https://evil.example"])
    sites.seen(store, "https://www.amazon.in/gp/css/order-history?ref=x")
    sites.seen(store, "https://smile.amazon.in/x")
    sites.seen(store, "https://other.example/x")  # not a signed-in site: nothing kept
    assert sites.origins_of(store, "amazon.in") == ["https://pay.amazon.in", "https://smile.amazon.in", "https://www.amazon.in"]
