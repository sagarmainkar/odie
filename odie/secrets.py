"""API keys: from the environment, else from the .env in Odie's folder (KEY=value lines; ~/.odie/.env).
Never logged, never sent to the phone. Settings can add or remove a key; the file stays readable only by the user."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
VALUE_RE = re.compile(r"^[A-Za-z0-9._\-:/+=~]+$")  # what load_secret reads back intact


def env_file() -> Path:
    # The settings folder's .env, from odie.home rather than config: config itself reads settings from this file.
    from odie.home import resolve
    return resolve().config_dir / ".env"


def _line_re(name: str) -> re.Pattern:
    # NAME=value, NAME="value with spaces" or NAME='value'; an unquoted value ends at a space or a # comment
    return re.compile(rf"""\s*(?:export\s+)?{re.escape(name)}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^'"\s#]+))""")


def load_secret(name: str, env_file_path: Path | None = None) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    try:
        text = (env_file_path or env_file()).read_text()
    except OSError:
        return None
    for line in text.splitlines():
        m = _line_re(name).match(line)
        if m:
            return next((g for g in m.groups() if g), None)
    return None


def _write(lines: list[str]) -> None:
    f = env_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".env.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write("".join(line + "\n" for line in lines))
        os.replace(tmp, f)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _lines() -> list[str]:
    try:
        return env_file().read_text().splitlines()
    except OSError:
        return []


def save_secret(name: str, value: str) -> None:
    """Add or replace NAME=value in the .env file, keeping every other line."""
    if not NAME_RE.match(name):
        raise ValueError("bad key name")
    if not VALUE_RE.match(value or ""):
        raise ValueError("That key has characters a key doesn't have (spaces, quotes or #).")
    lines = [ln for ln in _lines() if not _line_re(name).match(ln)]
    _write([*lines, f"{name}={value}"])


def remove_secret(name: str) -> bool:
    lines = _lines()
    kept = [ln for ln in lines if not _line_re(name).match(ln)]
    if len(kept) == len(lines):
        return False
    _write(kept)
    return True
