"""The browser's address policy (only public http(s), checked for every request a page makes) and finding the
browser on this computer."""
from pathlib import Path

import pytest

from odie.browser import find
from odie.browser.engine import public_policy


def _resolver(table):
    async def resolve(host):
        if host not in table:
            raise OSError("no such host")
        return table[host]
    return resolve


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/api/tasks", "http://localhost/", "http://10.1.2.3/", "http://172.16.5.4/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://100.101.102.103/", "http://[::1]/", "http://[fd00::1]/", "http://224.0.0.1/",
    "file:///etc/passwd", "data:text/html,hi", "chrome://settings", "ftp://example.com/", "http://router.home/", "http://nowhere.invalid/",
])
async def test_refused(url):
    allow = public_policy(_resolver({"localhost": ["127.0.0.1"], "router.home": ["192.168.1.1"], "example.com": ["93.184.215.14"]}))
    assert await allow(url) is False


@pytest.mark.parametrize("url", ["https://www.amazon.in/s?k=airpods", "http://93.184.215.14/", "https://example.com/a?b=c"])
async def test_allowed(url):
    allow = public_policy(_resolver({"www.amazon.in": ["52.95.120.67"], "example.com": ["93.184.215.14"]}))
    assert await allow(url) is True


async def test_a_host_resolving_to_any_private_address_is_refused():
    allow = public_policy(_resolver({"mixed.example": ["93.184.215.14", "10.0.0.5"]}))
    assert await allow("https://mixed.example/") is False


async def test_answers_are_cached():
    calls = []

    async def resolve(host):
        calls.append(host)
        return ["93.184.215.14"]
    allow = public_policy(resolve)
    for _ in range(5):
        assert await allow("https://example.com/x")
    assert calls == ["example.com"]


def test_finding_the_browser(monkeypatch, tmp_path):
    fake = tmp_path / "chrome"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ODIE_BROWSER", str(fake))
    assert find.browser_binary() == str(fake)
    monkeypatch.setenv("ODIE_BROWSER", "off")
    assert find.browser_binary() is None
    monkeypatch.setenv("ODIE_BROWSER", str(tmp_path / "missing"))
    assert find.browser_binary() is None
    monkeypatch.delenv("ODIE_BROWSER")
    monkeypatch.setattr(find, "CANDIDATES", [str(tmp_path / "nope"), str(fake)])
    monkeypatch.setattr(find.shutil, "which", lambda name: None)
    assert find.browser_binary() == str(fake)


async def test_a_lookup_that_fails_isnt_kept_or_called_private():
    from odie.browser.engine import Browser, BrowserError
    tries = []

    async def flaky(host):
        tries.append(host)
        if len(tries) == 1:
            raise OSError("no network")
        return ["93.184.215.14"]
    allow = public_policy(flaky)
    assert await allow("https://shop.example/") is False and "could not be found" in allow.reason("https://shop.example/")
    assert await allow("https://shop.example/") is True  # not cached: the Wi-Fi came back
    b = Browser(Path("/nonexistent"), binary="/bin/false", policy=public_policy(_resolver({})))
    with pytest.raises(BrowserError) as e:
        await b.open("t", "https://nowhere.example/")
    assert "couldn't find nowhere.example" in str(e.value) and "home network" not in str(e.value)


async def test_a_stuck_page_says_to_open_it_again(monkeypatch):
    from odie.browser.engine import Browser, BrowserError
    b = Browser(Path("/nonexistent"), binary="/bin/false")

    async def session(tab, create, isolated=False):
        return "s1"
    monkeypatch.setattr(b, "_session", session)

    async def stuck(s):
        raise TimeoutError()
    with pytest.raises(BrowserError) as e:
        await b._act("t", False, stuck)
    assert "browser_open" in str(e.value)


def test_quick_facts_and_prices_go_to_different_tools():
    from odie.agent.prompt import ALL_CAPS, Who, rules_text
    with_browser = rules_text(Who(caps=ALL_CAPS | {"browser"}), gated=True)
    web_line = next(line for line in with_browser.splitlines() if "use web_search" in line)
    assert "prices" not in web_line and "browser_open" in with_browser
    without = rules_text(Who(caps=ALL_CAPS), gated=True)
    assert "prices" in next(line for line in without.splitlines() if "use web_search" in line)  # unchanged without a browser
