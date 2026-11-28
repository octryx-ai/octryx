"""One placeholder vocabulary for branch naming rules (Coding setup, Work planning, workflow runs)."""

from __future__ import annotations

import re

DEFAULT_BRANCH_RULE = "{type}/{key}-{slug}"
DEFAULT_BRANCH_TYPE = "feature"


def render_branch(rule: str | None, *, branch_type: str, key: str, slug: str) -> str:
    text = str(rule or "").strip() or DEFAULT_BRANCH_RULE
    name = text.replace("{type}", branch_type or DEFAULT_BRANCH_TYPE).replace("{key}", key).replace("{slug}", slug)
    return re.sub(r"/+", "/", name.replace("{", "").replace("}", "")).strip("/-")


__all__ = ["DEFAULT_BRANCH_RULE", "DEFAULT_BRANCH_TYPE", "render_branch"]
