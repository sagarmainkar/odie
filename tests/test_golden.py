"""Byte-for-byte: what the model sees. A failure means prompt or tool text changed; if that was intended,
regenerate with `uv run python -m tests.golden_render --write` and review the diff in the PR."""
import pytest

from tests.golden_render import GOLDEN, render


def test_snapshot_covers_every_rendered_text(isolated_settings, tmp_path):
    assert sorted(render(tmp_path)) == sorted(p.name for p in GOLDEN.iterdir())


@pytest.mark.parametrize("name", sorted(p.name for p in GOLDEN.iterdir()) if GOLDEN.exists() else [])
def test_model_sees_exactly_the_golden_text(name, isolated_settings, tmp_path):
    assert render(tmp_path)[name] == (GOLDEN / name).read_text(), f"{name} changed"
