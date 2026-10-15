import logging
import os

import pytest

from odie.plugins import mcp
from odie.plugins.mcp import MASK, masked, scrub, secret_part, toolset_for, unmask

ZAPIER = "https://mcp.zapier.com/api/mcp/s/ZjM4NzQ1YTMtOWQ2Yi00ZTEyLWE3ZjAtZDc5YTBkNTRhMTQ3OjhlMmE1ZWQ0/mcp"
COMPOSIO = "https://mcp.composio.dev/composio/server/2f1c9a3e-8b7d-4e6f-9a1b-3c5d7e9f1a2b/mcp?user_id=asha"


def test_masks_secrets_in_url_args_env_and_headers():
    spec = {"url": "https://api.example/mcp?api_key=abc123&region=eu", "headers": {"Authorization": "Bearer x"},
            "command": "npx", "args": ["-y", "server", "--token", "t-999", "--api-key=k-1", "--port", "8080", "sk-abcdefghijklmnop"],
            "env": {"GITHUB_TOKEN": "ghp_x"}, "title": "Example"}
    m = masked(spec)
    assert m["url"] == f"https://api.example/mcp?api_key={MASK}&region=eu"
    assert m["args"] == ["-y", "server", "--token", MASK, f"--api-key={MASK}", "--port", "8080", MASK]
    assert m["env"] == {"GITHUB_TOKEN": MASK} and m["headers"] == {"Authorization": MASK} and m["title"] == "Example"
    assert spec["args"][3] == "t-999"  # the original is untouched


def test_unmask_keeps_real_secrets_when_the_masked_form_comes_back():
    old = {"url": "https://api.example/mcp?api_key=abc123", "args": ["--token", "t-999", "--port", "8080"], "env": {"K": "v"}}
    back = masked(old)
    back["args"][3] = "9090"  # The user changed the port only
    new = unmask(back, old)
    assert new["url"] == old["url"] and new["args"] == ["--token", "t-999", "--port", "9090"] and new["env"] == {"K": "v"}
    changed = unmask({**back, "url": "https://other.example/mcp?api_key=new"}, old)
    assert changed["url"] == "https://other.example/mcp?api_key=new"


def test_stdio_servers_get_a_usable_environment(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("USER", "asha")
    t = toolset_for("x", {"command": "npx", "args": ["-y", "pkg"], "env": {"K": "v"}})
    env = t._connection_params.server_params.env
    assert env["K"] == "v" and env["USER"] == "asha" and "SHELL" in env and "LANG" in env
    for d in ("/opt/homebrew/bin", "/usr/local/bin", ".local/bin"):
        assert d in env["PATH"]


def test_app_tool_approval_names_the_app_and_keeps_args_off_the_lock_screen(tmp_path):
    from odie.app.runner import approval_from_confirmation, push_body
    from odie.plugins import mcp
    from odie.store.db import Store
    s = Store(tmp_path / "a.db")
    s.init_schema()
    mcp.TOOL_APP.clear()
    mcp.TOOL_APP["write_note"] = "Obsidian notes"

    class FC:
        id = "c1"
        args = {"originalFunctionCall": {"name": "write_note", "args": {"path": "Inbox/idea.md", "text": "private thought"}}}
    a = approval_from_confirmation(FC(), "i1", "s1", s)
    assert a["summary"].startswith("Write note in Obsidian notes: path: Inbox/idea.md")
    assert a["detail"]["app"] == "Obsidian notes"
    assert push_body(a) == "Write note in Obsidian notes" and "private" not in push_body(a)
    mcp.TOOL_APP.clear()



def test_path_secrets_are_masked_and_restored():
    assert masked({"url": ZAPIER})["url"] == f"https://mcp.zapier.com/api/mcp/s/{MASK}/mcp"
    assert masked({"url": COMPOSIO})["url"] == f"https://mcp.composio.dev/composio/server/{MASK}/mcp?user_id=asha"
    old = {"url": ZAPIER, "headers": {"Authorization": "Bearer tok-ABCdef1234567890XYZ"}, "description": "Zaps"}
    back = {**masked(old), "description": "My zaps"}
    assert unmask(back, old) == {**old, "description": "My zaps"}
    assert unmask(masked({"url": COMPOSIO}), {"url": COMPOSIO})["url"] == COMPOSIO


@pytest.mark.parametrize("url", [
    "https://example.com/blog/2026-10-06-meeting-notes", "https://docs.example.com/v1.2.3/reference/servers",
    "https://api.example.com/mcp/servers/filesystem", "https://github.com/modelcontextprotocol/servers/tree/main/src",
    "http://127.0.0.1:8770/mcp?region=eu&mode=read",
])
def test_ordinary_links_are_not_masked(url):
    assert masked({"url": url})["url"] == url
    assert all(not secret_part(p) for p in url.split("/"))


def test_a_changed_link_must_be_typed_again():
    old = {"url": ZAPIER}
    back = masked(old)
    with pytest.raises(ValueError):
        unmask({**back, "url": back["url"].replace("mcp.zapier.com", "evil.example")}, old)  # the hidden part never goes to a new host
    with pytest.raises(ValueError):
        unmask({**back, "url": back["url"].replace("/s/", "/s/x/")}, old)  # not the same shape: nothing to match it with
    with pytest.raises(ValueError):
        unmask(back, {})  # nothing saved
    with pytest.raises(ValueError):  # a saved key never goes to a new address either
        unmask({"url": "https://evil.example/mcp", "headers": {"Authorization": MASK}},
               {"url": "https://mcp.zapier.com/api/mcp/mcp", "headers": {"Authorization": "Bearer tok-ABCdef1234567890XYZ"}})


def test_reasons_are_scrubbed():
    spec = {"url": ZAPIER, "headers": {"Authorization": "Bearer tok-ABCdef1234567890XYZ"}}
    secret = ZAPIER.split("/")[-2]
    text = f"Client error '401 Unauthorized' for url '{ZAPIER}' (sent tok-ABCdef1234567890XYZ)"
    out = scrub(text, spec)
    assert secret not in out and "tok-ABCdef1234567890XYZ" not in out and MASK in out and "401 Unauthorized" in out
    assert scrub("Connection refused", spec) == "Connection refused"


async def test_a_failing_server_has_a_scrubbed_reason(isolated_settings, monkeypatch):
    mcp.write_config({"zaps": {"url": ZAPIER}})

    async def boom(spec, timeout):
        raise RuntimeError(f"Client error '401 Unauthorized' for url '{spec['url']}'")
    monkeypatch.setattr(mcp, "probe_tools", boom)
    [e] = await mcp.load_servers()
    assert e.status == "failed" and ZAPIER.split("/")[-2] not in e.reason and MASK in e.reason


def test_request_logs_mask_secret_urls(caplog):
    mcp.install_log_masking()
    mcp.install_log_masking()  # once is enough; twice adds nothing
    assert sum(isinstance(f, mcp.MaskUrls) for f in logging.getLogger("httpx").filters) == 1
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info('HTTP Request: %s %s "%s"', "POST", ZAPIER, "HTTP/1.1 200 OK")
    assert ZAPIER.split("/")[-2] not in caplog.text and f"/s/{MASK}/mcp" in caplog.text and "200 OK" in caplog.text
    caplog.clear()
    try:
        raise RuntimeError(f"Client error '401 Unauthorized' for url '{ZAPIER}'")
    except RuntimeError:
        logging.getLogger("odie.test").warning("tool call failed", exc_info=True)  # a traceback, through the root handlers
    assert "401 Unauthorized" in caplog.text and "Traceback" in caplog.text and ZAPIER.split("/")[-2] not in caplog.text


def test_mcp_json_is_owner_only(isolated_settings):
    mcp.write_config({"x": {"url": "https://example.com/mcp"}})
    assert os.stat(mcp.mcp_path()).st_mode & 0o777 == 0o600
    mcp.mcp_path().chmod(0o644)  # written before this fix, or by hand
    assert mcp.read_config()[0] == {"x": {"url": "https://example.com/mcp"}}
    assert os.stat(mcp.mcp_path()).st_mode & 0o777 == 0o600
