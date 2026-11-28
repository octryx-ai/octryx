"""Deleting a corporate-identity profile or template through the service the admin routes call."""

from __future__ import annotations

import pytest

from app.services.corp_identity_service import delete_corp_identity_profile, delete_corp_identity_template


@pytest.mark.asyncio
async def test_deleting_an_unknown_profile_reports_it_missing(db):
    with pytest.raises(FileNotFoundError):
        await delete_corp_identity_profile(db, "no-such-profile")


@pytest.mark.asyncio
async def test_deleting_a_template_of_an_unknown_profile_reports_it_missing(db):
    with pytest.raises(FileNotFoundError, match="no-such-profile"):
        await delete_corp_identity_template(db, "no-such-profile", "no-such-template")
