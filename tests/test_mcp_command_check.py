"""The API's refusal of an MCP spec that is only a way to run text (odie.plugins.mcp.command_problem): the review of
25 Oct 2026 walked around the name lists with wrappers, versioned names, joined flags and spaces; now it looks through
them. A real server (npx, uvx, python -m, node file.js) still runs: saving a server is running code by design."""
import os

import pytest

from odie.plugins.mcp import command_problem

REFUSED = [
    ({"command": "/bin/sh", "args": ["-c", "id > /tmp/x"]}, "shell"),
    ({"command": "env", "args": ["sh", "-c", "id"]}, "shell"),                       # a wrapper around a shell
    ({"command": "/usr/bin/env", "args": ["python3", "-c", "import os"]}, "code"),
    ({"command": "xargs", "args": ["sh", "-c", "id"]}, "shell"),
    ({"command": "nohup", "args": ["nice", "zsh", "-c", "id"]}, "shell"),           # wrappers inside wrappers
    ({"command": "env", "args": ["FOO=1", "bash", "-c", "id"]}, "shell"),            # env's assignments come first
    ({"command": " sh", "args": ["-c", "id"]}, "shell"),                              # a space around the name
    ({"command": "zsh-5.9", "args": ["-c", "id"]}, "shell"),                          # a versioned name
    ({"command": "python3.12", "args": ["-c", "import os"]}, "code"),
    ({"command": "python3", "args": ["-cimport os"]}, "code"),                        # the code joined to the flag
    ({"command": "python3", "args": ["-Sc", "import os"]}, "code"),                   # a cluster of flags
    ({"command": "node", "args": ["--eval=1"]}, "code"),
    ({"command": "node", "args": ["-pe", "1"]}, "code"),
    ({"command": "node", "args": ["--require", "/tmp/x.js", "server.js"]}, "code"),  # code loaded before the server
    ({"command": "node", "args": ["--import", "/tmp/x.mjs", "server.js"]}, "code"),
    ({"command": "perl", "args": ["-E", "say 1"]}, "code"),
    ({"command": "perl", "args": ["-MFoo", "server.pl"]}, "code"),
    ({"command": "deno", "args": ["eval", "1"]}, "code"),
    ({"command": "node", "args": ["server.js"], "env": {"NODE_OPTIONS ": "--require x"}}, "NODE_OPTIONS"),  # a space in the key
    ({"command": "python3", "args": ["-m", "srv"], "env": {"PYTHONHOME": "/tmp/x"}}, "PYTHONHOME"),
    ({"command": "python3", "args": ["-m", "srv"], "env": {"path": "/tmp/evil:/usr/bin"}}, "PATH"),
]
ALLOWED = [
    {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
    {"command": "python3", "args": ["-m", "my_server"]},
    {"command": "uvx", "args": ["mcp-server-fetch"]},
    {"command": "node", "args": ["server.js", "--port", "3000"]},
    {"command": "/opt/homebrew/bin/node", "args": ["dist/index.js"]},
    {"command": "python3", "args": ["server.py", "--config", "c.json"]},   # --config is not -c
    {"command": "docker", "args": ["run", "-i", "--rm", "mcp/server"]},
    {"command": "env", "args": ["FOO=1", "npx", "-y", "some-server"]},
    {"command": "node", "args": ["server.js"], "env": {"API_KEY": "x", "HOME": "/Users/me"}},
    {"url": "https://mcp.example/s/abc"},
]


@pytest.mark.parametrize("spec,word", REFUSED)
def test_a_way_to_run_text_is_refused_however_it_is_spelled(spec, word):
    why = command_problem(spec)
    assert why is not None and word.lower() in why.lower(), (spec, why)


@pytest.mark.parametrize("spec", ALLOWED)
def test_a_real_server_still_runs(spec):
    assert command_problem(spec) is None, spec


def test_a_symlink_to_a_shell_is_a_shell(tmp_path):
    link = tmp_path / "helper"
    os.symlink("/bin/sh", link)
    assert command_problem({"command": str(link), "args": ["-c", "id"]}) == "a shell isn't an MCP server"
