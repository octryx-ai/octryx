"""The version content writer, digests and immutability (database)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Approval, Skill, SkillBlob, SkillCategory, SkillVersion
from app.models.runtime.governed_revision import ImmutableRevisionError
from app.services.skill_catalog.bundle import BundleFile
from app.services.skill_catalog.errors import SkillCatalogError
from app.services.skill_catalog.versions import (
    VersionContent,
    content_digest,
    new_draft_row,
    sync_identity,
    write_content,
)
from tests.skill_catalog.support import publish_chat_skill

# Two published chat-only skills as a fixture.
pytestmark = pytest.mark.usefixtures("chat_skills")

SKILL_MD = "---\nname: {name}\ndescription: Check things.\n---\n\n# Checks\n\nRun the checks.\n"


async def _category(db, key: str = "ops") -> SkillCategory:
    category = SkillCategory(key=f"{key}-{uuid.uuid4().hex[:6]}", label=key)
    db.add(category)
    await db.flush()
    return category


async def _skill(db, name: str | None = None) -> Skill:
    skill = Skill(id=str(uuid.uuid4()), name=name or f"check-{uuid.uuid4().hex[:6]}", category="ops")
    db.add(skill)
    await db.flush()
    return skill


def _content(skill: Skill, category: SkillCategory, **overrides) -> VersionContent:
    files = overrides.pop("files", [BundleFile("SKILL.md", SKILL_MD.format(name=skill.name))])
    return VersionContent(files=files, extension={}, category_id=category.id, **overrides)


@pytest.mark.asyncio
async def test_write_content_stores_blobs_digests_and_parsed_view(db):
    category, skill = await _category(db), await _skill(db)
    row = await new_draft_row(db, skill, actor_id=None, note="first", base_version=None)
    db.add(row)
    await write_content(db, skill, row, _content(skill, category, files=[
        BundleFile("SKILL.md", SKILL_MD.format(name=skill.name)), BundleFile("./references/a.md", "ref")]))
    assert row.version == 1 and row.state == "draft"
    assert row.frontmatter == {"name": skill.name, "description": "Check things."}
    assert row.body == "\n# Checks\n\nRun the checks.\n"
    assert [entry["path"] for entry in row.files] == ["SKILL.md", "references/a.md"]
    assert row.digest == content_digest(row) and row.bundle_digest.startswith("sha256:")
    stored = {blob.sha256 for blob in (await db.execute(select(SkillBlob))).scalars()}
    assert {entry["sha256"] for entry in row.files} <= stored
    files = [BundleFile("SKILL.md", SKILL_MD.format(name=skill.name)), BundleFile("references/a.md", "ref")]
    before = row.digest
    await write_content(db, skill, row, _content(skill, category, files=list(files)))
    assert row.digest == before
    await write_content(db, skill, row, _content(skill, category, files=list(files), available_octryx_claude=False))
    assert row.digest != before  # availability is reviewed content


@pytest.mark.asyncio
@pytest.mark.parametrize(("files", "code"), [
    ([BundleFile("README.md", "x")], "skill_md_missing"),
    ([BundleFile("SKILL.md", "no frontmatter")], "skill_spec_invalid"),
    ([BundleFile("SKILL.md", SKILL_MD.format(name="wrong-name"))], "skill_spec_invalid"),
    ([BundleFile("SKILL.md", "x"), BundleFile("../x", "y")], "skill_path_traversal"),
])
async def test_write_content_refuses_invalid_bundles(db, files, code):
    category, skill = await _category(db), await _skill(db)
    row = await new_draft_row(db, skill, actor_id=None, note=None, base_version=None)
    db.add(row)
    with pytest.raises(SkillCatalogError) as caught:
        await write_content(db, skill, row, _content(skill, category, files=files))
    assert caught.value.code == code and caught.value.status == 422


@pytest.mark.asyncio
async def test_write_content_requires_an_active_category(db):
    category, skill = await _category(db), await _skill(db)
    row = await new_draft_row(db, skill, actor_id=None, note=None, base_version=None)
    db.add(row)
    with pytest.raises(SkillCatalogError) as missing:
        await write_content(db, skill, row, VersionContent(files=[], extension={}, category_id=None))
    assert missing.value.code == "skill_category_required"
    from app.time_utils import utc_now
    category.archived_at = utc_now()
    with pytest.raises(SkillCatalogError) as archived:
        await write_content(db, skill, row, _content(skill, category))
    assert archived.value.code == "skill_category_archived"


@pytest.mark.asyncio
async def test_a_published_version_is_immutable_and_one_open_draft_per_skill(db):
    admin = (await db.execute(select(Skill).where(Skill.name == "alert-diagnosis"))).scalar_one()
    published = await db.get(SkillVersion, admin.published_version_id)
    published.body = "changed"
    with pytest.raises(ImmutableRevisionError):
        await db.flush()
    await db.rollback()

    category, skill = await _category(db), await _skill(db)
    first = await new_draft_row(db, skill, actor_id=None, note=None, base_version=None)
    db.add(first)
    await write_content(db, skill, first, _content(skill, category))
    second = await new_draft_row(db, skill, actor_id=None, note=None, base_version=None)
    db.add(second)
    second.digest = second.bundle_digest = "x"
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_a_stored_name_outside_the_spec_is_a_warning_and_the_listing_mirrors_the_version(db):
    actor = (await db.execute(select(Approval.requested_by).limit(1))).scalar_one()
    skill, version = await publish_chat_skill(db, "Stored Name", approver_id=actor, description="Stored skill",
                                              category="Team Stuff", body="# Stored", required_tools=("a_tool",))
    assert {issue["code"] for issue in version.security_report["spec"]} == {"skill_name_invalid"}
    assert skill.published_version_id == version.id and skill.category == "team-stuff"
    await sync_identity(db, skill, None)
    assert not skill.available_platform_chat and skill.published_version_id is None
