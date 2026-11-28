"""Configured template states for Office acceptance."""

import pytest

from app.services.office.neutral_presentation_template import NEUTRAL_TEMPLATE_PATH, build_neutral_presentation_template
from app.services.office.presentation_fallback import set_presentation_fallback_mode
from app.tools.context import ToolContext
from app.tools.presentation_impl._presentation_template import TemplateResolutionError, resolve_composer_template


def test_neutral_template_is_reproducible():
    assert NEUTRAL_TEMPLATE_PATH.read_bytes() == build_neutral_presentation_template()


async def test_fallback_can_be_disabled_and_broken_profile_is_not_substituted(db, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from app.services import corp_identity_service as ci

    async def no_profile(_db):
        return None

    monkeypatch.setattr(ci, "get_default_corp_identity_profile", no_profile)
    context = ToolContext(user_id="u", project_ids=[], roles=["admin"], session_id="s", db=db,
                          workspace_root=str(tmp_path), project_config={})
    path, metadata = await resolve_composer_template(context)
    assert path == NEUTRAL_TEMPLATE_PATH
    assert metadata["source"] == "builtin_neutral_template"
    await set_presentation_fallback_mode(db, mode="disabled", updated_by=None)
    with pytest.raises(TemplateResolutionError) as refused:
        await resolve_composer_template(context)
    assert refused.value.code == "presentation_template_unconfigured"
    await set_presentation_fallback_mode(db, mode="builtin_neutral", updated_by=None)

    async def broken_profile(_db):
        return {"id": "missing", "name": "Configured profile"}

    monkeypatch.setattr(ci, "get_default_corp_identity_profile", broken_profile)
    monkeypatch.setattr(ci, "resolve_corp_identity_composer_template", lambda _p: SimpleNamespace(path="missing.potx"))
    with pytest.raises(TemplateResolutionError) as refused:
        await resolve_composer_template(context)
    assert refused.value.code == "corp_identity_template_missing"
