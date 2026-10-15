"""Runtime settings, from the environment or the .env in Odie's folder (KEY=value lines, like the keys).
Odie's own: ODIE_HOME, ODIE_DATA_DIR, ODIE_CONFIG_DIR, ODIE_MODEL, ODIE_MEMORY_FILE, ODIE_PREFETCH, ODIE_HOST,
ODIE_PORT, ODIE_PUBLIC_URL, ODIE_APP_NAME, ODIE_USER_ID, ODIE_TIMEZONE, ODIE_EMBED_IDLE_MINUTES,
ODIE_LOCALE, ODIE_CURRENCY, ODIE_ADDONS, ODIE_VOICE (off: no local voice worker), ODIE_VOICE_PORT (8771). Others: each
built-in provider's address, LM_STUDIO_BASE_URL, OLLAMA_BASE_URL, OPENAI_BASE_URL, OPENROUTER_BASE_URL, GEMINI_BASE_URL and
ANTHROPIC_BASE_URL (odie.models.provider_base_url, read on every request). Add-ons read their own."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from odie import home as _home
from odie import region


def _raw(name: str, default: str | None = None) -> str | None:
    """A setting from the environment, else from the settings .env (load_secret checks both, in that order)."""
    from odie.secrets import load_secret
    return load_secret(name) or default


def _get(name: str, default: str | None = None) -> str | None:
    return _raw(f"ODIE_{name}", default)


def _path(name: str, default: str) -> Path:
    return Path(_raw(name, default)).expanduser()


def _addons_dirs() -> list[Path]:
    """ODIE_ADDONS (folders separated by ":"; set but empty means none), else <home>/addons. A test copy without a home
    loads none."""
    import os
    v = os.environ.get("ODIE_ADDONS")  # read directly: an empty value is a choice, not "unset"
    if v is None:
        v = _get("ADDONS")
    if v is not None:
        return [Path(p).expanduser() for p in v.split(":") if p.strip()]
    home = _layout().home
    return [home / "addons"] if home else []


def _layout() -> _home.Layout:
    return _home.resolve()


def _memory_file() -> Path:
    if v := _get("MEMORY_FILE"):
        return Path(v).expanduser()
    lay = _layout()
    return lay.home / "memories.md" if lay.home else lay.data_dir / "memories.md"


def _identity() -> tuple[str, str]:
    from odie.identity import DEFAULT_APP, DEFAULT_USER, stored_identity
    app, user = stored_identity(_layout().data_dir / "sessions.db") or (DEFAULT_APP, DEFAULT_USER)
    return _get("APP_NAME", app), _get("USER_ID", user)


def _timezone() -> str:
    tz = _get("TIMEZONE")
    return tz if tz and region.valid_zone(tz) else region.system_timezone()


def _locale() -> str:
    return region.normalize_locale(_get("LOCALE")) or region.system_locale()


def _currency() -> str:
    return (_get("CURRENCY") or region.currency_for(region.country_of(_locale()))).upper()


def phone_address() -> str:
    """The address a phone reaches Odie at (ODIE_PUBLIC_URL, Tailscale's), or "" when there's none: the default is this
    computer's own address, which no phone can open."""
    from urllib.parse import urlsplit
    url = settings.public_url.rstrip("/")
    return "" if (urlsplit(url).hostname or "") in ("", "localhost", "127.0.0.1", "::1") else url


@dataclass(frozen=True)
class Settings:
    home: Path | None = field(default_factory=lambda: _layout().home)
    data_dir: Path = field(default_factory=lambda: _layout().data_dir)
    config_dir: Path = field(default_factory=lambda: _layout().config_dir)  # .env, SOUL.md, mcp.json, user skills
    addons_dirs: list[Path] = field(default_factory=_addons_dirs)
    lm_studio_base_url: str = field(default_factory=lambda: _raw("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"))
    lm_studio_api_key: str = "lm-studio"
    model_id: str = field(default_factory=lambda: _get("MODEL", "gemma-4-26b-a4b-it-qat"))
    prefetch: bool = field(default_factory=lambda: _get("PREFETCH", "1") not in ("0", "false", "no"))
    embed_idle_minutes: int = field(default_factory=lambda: int(_get("EMBED_IDLE_MINUTES", "15")))  # the embedding service unloads its model after this long idle; 0: never
    app_name: str = field(default_factory=lambda: _identity()[0])  # existing chats keep theirs (odie.identity)
    user_id: str = field(default_factory=lambda: _identity()[1])
    timezone: str = field(default_factory=_timezone)  # the computer's own (odie.region)
    locale: str = field(default_factory=_locale)  # BCP 47, e.g. en-IN: how the app formats dates and numbers
    currency: str = field(default_factory=_currency)
    host: str = field(default_factory=lambda: _get("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(_get("PORT", "8000")))
    web_dist: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "web" / "dist")
    memory_file: Path = field(default_factory=_memory_file)
    review_every_turns: int = 10
    public_url: str = field(default_factory=lambda: _get("PUBLIC_URL", "http://localhost:8000"))  # the phone's HTTPS address

    @property
    def country(self) -> str:
        return region.country_of(self.locale)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    @property
    def sessions_db_path(self) -> Path:
        return self.data_dir / "sessions.db"

    @property
    def vapid_path(self) -> Path:
        return self.data_dir / "vapid.json"


settings = Settings()
