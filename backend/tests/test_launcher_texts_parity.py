"""Every launcher text is a catalog key (run.launcher.*, sent as the run contract's prompt_texts) and the launcher
keeps the same seed as its fallback, so a server without the texts and the launcher read alike."""

from __future__ import annotations

import ast
from pathlib import Path

from app.services.prompt_catalog.seeds.run import SPECS

PIPELINE = Path(__file__).resolve().parents[2] / "clients" / "octryx-claude" / "octryx_claude" / "pipeline_texts.py"


def _fallbacks() -> dict[str, str]:
    tree = ast.parse(PIPELINE.read_text(encoding="utf-8"))
    node = next(item for item in tree.body if isinstance(item, ast.Assign)
                and getattr(item.targets[0], "id", "") == "FALLBACK_TEXTS")
    return ast.literal_eval(node.value)


def test_every_launcher_key_has_the_same_seed_as_the_launchers_fallback():
    catalog = {spec.key: spec.seed for spec in SPECS if spec.key.startswith("run.launcher.")}
    assert catalog == _fallbacks()
    for key in ("run.launcher.wrapper_denied", "run.launcher.plain_form", "run.launcher.fail_closed",
                "run.launcher.proof_unavailable", "run.launcher.takeover_denied", "run.launcher.sandbox_browser"):
        assert "Next:" in catalog[key], key
