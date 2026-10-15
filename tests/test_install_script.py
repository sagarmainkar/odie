"""scripts/install.sh builds the same things `odie update` does (odie.cli.build_steps): Odie's packages, the voice
worker's and the embedding service's environments unless switched off, and the web app. A fresh install that skipped
one of them hid the "EmbeddingGemma 2, on this Mac" choice (14 Oct 2026)."""
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "scripts" / "install.sh").read_text()


def test_the_installer_builds_every_worker_the_update_builds():
    assert 'build_in "$APP" uv sync --frozen' in SCRIPT
    assert 'if [ "${ODIE_VOICE:-on}" != "off" ]; then build_in "$APP/voice_server" uv sync --frozen; fi' in SCRIPT
    assert 'if [ "${ODIE_EMBED:-on}" != "off" ]; then build_in "$APP/embed_server" uv sync --frozen; fi' in SCRIPT
    assert 'build_in "$APP/web" npm ci' in SCRIPT and 'build_in "$APP/web" npm run build' in SCRIPT
