"""Import — Git inspect/import with provenance, marketplace entries, uploads, licences."""

from __future__ import annotations

import base64
import io
import os
import stat
import zipfile

import pytest
from sqlalchemy import select

from app.models import AuditLog, Skill, SkillSource, SkillUpstreamSnapshot, SkillVersion
from app.services.skill_catalog.bundle import bundle_files
from app.services.skill_catalog.errors import SkillCatalogError
from app.services.skill_catalog.versions import content_of, write_content
from tests.policy_engine_support import bearer, make_user
from tests.skill_catalog.fake_git import COMMUNITY, HASHICORP, MARKET_LATER, NEW, OFFICIAL, OLD
from tests.skill_catalog.support import BASE, category, skill_md

STYLE_PATH = "terraform/code-generation/skills/terraform-style-guide"


async def _inspect(client, admin, **payload):
    return await client.post(f"{BASE}/import/inspect", json=payload, headers=bearer(admin))


async def _import(client, admin, **payload):
    return await client.post(f"{BASE}/import/git", json=payload, headers=bearer(admin))


@pytest.mark.asyncio
async def test_import_endpoints_are_platform_admin_only(client, db, fake_git):
    member = await make_user(db, admin=False)
    for path in ("/import/inspect", "/import/git", "/import/upload"):
        assert (await client.post(f"{BASE}{path}", json={}, headers=bearer(member))).status_code == 403
    assert (await client.get(f"{BASE}/sources", headers=bearer(member))).status_code == 403
    assert (await client.put(f"{BASE}/settings", json={}, headers=bearer(member))).status_code == 403
    assert fake_git.calls == []


@pytest.mark.asyncio
async def test_inspect_lists_the_skills_of_a_vendor_repository_at_one_commit(client, db, fake_git):
    admin = await make_user(db, admin=True)
    response = await _inspect(client, admin, url=HASHICORP, ref=OLD, path="terraform/code-generation/skills")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["commit"] == OLD and body["licence"] == {"spdx": "MPL-2.0", "source": "repository"}
    skills = {item["name"]: item for item in body["skills"]}
    assert set(skills) == {"terraform-style-guide", "terraform-test"}
    style = skills["terraform-style-guide"]
    assert style["path"] == STYLE_PATH and style["importable"] and style["scripts"] == []
    assert style["licence"] == {"spdx": "MPL-2.0", "source": "plugin", "allowed": True}
    assert style["existing"] is None and style["description"].startswith("Generate Terraform")
    assert body["mcp_servers"] == [] and ("resolve", HASHICORP, OLD, None) in fake_git.calls


@pytest.mark.asyncio
async def test_import_creates_a_pinned_draft_with_provenance_licence_and_snapshot(client, db, fake_git):
    admin = await make_user(db, admin=True)
    terraform = (await category(db, "iac.terraform")).id
    response = await _import(client, admin, url=HASHICORP, ref=OLD, path="terraform/code-generation/skills",
                             commit=OLD, trust="official", items=[{"kind": "skill", "path": STYLE_PATH,
                                                                   "category_id": terraform, "tags": ["HCL"]}])
    assert response.status_code == 201, response.text
    imported = response.json()["imported"][0]
    skill = await db.get(Skill, imported["skill_id"])
    assert skill.name == "terraform-style-guide" and skill.tracking_mode == "pinned" and skill.pinned_commit == OLD
    assert skill.upstream_path == STYLE_PATH and skill.tags == ["hcl"] and skill.category == "iac.terraform"
    assert skill.published_version_id is None and not skill.available_platform_chat
    source = await db.get(SkillSource, skill.source_id)
    assert (source.url, source.ref, source.trust, source.label) == (HASHICORP, OLD, "official", "hashicorp/agent-skills")
    row = (await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill.id))).scalar_one()
    assert row.state == "draft" and row.licence_spdx == "MPL-2.0"
    assert (row.upstream_source_id, row.upstream_path, row.upstream_commit) == (source.id, STYLE_PATH, OLD)
    files = {item.path: item.content for item in await bundle_files(db, row.files)}
    assert set(files) == {"SKILL.md", "LICENSE"} and files["LICENSE"].startswith("Mozilla Public License")
    snapshot = (await db.execute(select(SkillUpstreamSnapshot))).scalar_one()
    assert snapshot.bundle_digest == row.upstream_bundle_digest == row.bundle_digest
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "skill_catalog.imported"))).scalar_one()
    assert audit.details["commit"] == OLD and audit.resource_id == skill.id

    again = await _import(client, admin, url=HASHICORP, ref=OLD, commit=OLD,
                          items=[{"path": STYLE_PATH, "category_id": terraform}])
    assert again.status_code == 409 and again.json()["detail"]["code"] == "skill_import_use_update"
    listed = (await _inspect(client, admin, url=HASHICORP, ref=OLD, path="terraform/code-generation/skills")).json()
    style = next(item for item in listed["skills"] if item["name"] == "terraform-style-guide")
    assert style["existing"] == {"skill_id": skill.id, "relation": "update", "kind": "skill"}
    moved = (await _inspect(client, admin, url=HASHICORP, ref=NEW, path="plugins/terraform/skills")).json()
    style = next(item for item in moved["skills"] if item["name"] == "terraform-style-guide")
    assert style["existing"]["relation"] == "name_taken"  # another path: the upstream check follows moves


@pytest.mark.asyncio
async def test_follow_needs_a_branch_and_unknown_items_are_refused(client, db, fake_git):
    admin = await make_user(db, admin=True)
    terraform = (await category(db, "iac.terraform")).id
    pinned_ref = await _import(client, admin, url=HASHICORP, ref=OLD, commit=OLD,
                               items=[{"path": STYLE_PATH, "category_id": terraform, "tracking_mode": "follow"}])
    assert pinned_ref.json()["detail"]["code"] == "skill_follow_requires_branch"
    missing = await _import(client, admin, url=HASHICORP, ref="main", commit=NEW,
                            items=[{"path": STYLE_PATH, "category_id": terraform}])
    assert missing.json()["detail"]["code"] == "skill_import_item_not_found"
    new_path = "plugins/terraform/skills/terraform-style-guide"
    follow = await _import(client, admin, url=HASHICORP, ref="main", commit=NEW,
                           items=[{"path": new_path, "category_id": terraform, "tracking_mode": "follow"}])
    assert follow.status_code == 201, follow.text
    skill = await db.get(Skill, follow.json()["imported"][0]["skill_id"])
    assert skill.tracking_mode == "follow" and skill.pinned_commit is None
    files = await bundle_files(db, (await db.get(SkillVersion, (await db.execute(select(SkillVersion.id).where(
        SkillVersion.skill_id == skill.id))).scalar_one())).files)
    kinds = {item.path for item in files}
    assert kinds == {"SKILL.md", "SECURITY.md", "LICENSE"}
    no_category = await _import(client, admin, url=HASHICORP, ref=OLD, commit=OLD, items=[
        {"path": "terraform/code-generation/skills/terraform-test", "category_id": "nope"}])
    assert no_category.json()["detail"]["code"] == "skill_category_required"


@pytest.mark.asyncio
async def test_the_official_marketplace_entry_is_an_mcp_server_entry(client, db, fake_git):
    admin = await make_user(db, admin=True)
    inspected = await _inspect(client, admin, url=OFFICIAL, ref="main", marketplace_plugin="terraform")
    assert inspected.status_code == 200, inspected.text
    body = inspected.json()
    assert body["commit"] == MARKET_LATER and body["path"] == "external_plugins/terraform"
    assert body["plugin"]["author"] == "HashiCorp" and body["plugin"]["category"] == "development"
    assert body["skills"] == [] and len(body["mcp_servers"]) == 1
    server = body["mcp_servers"][0]
    assert server["name"] == "terraform" and server["licence"]["spdx"] == "Apache-2.0"
    assert server["launch_spec"]["image"] == "hashicorp/terraform-mcp-server:0.4.0"
    assert server["launch_spec"]["passthrough"] == ["TFE_TOKEN"] and server["launch_spec"]["command"] == "docker"
    early = await _inspect(client, admin, url=OFFICIAL, ref="main", marketplace_plugin="early")
    assert early.status_code == 422 and early.json()["detail"]["code"] == "plugin_source_missing"
    unknown = await _inspect(client, admin, url=OFFICIAL, ref="main", marketplace_plugin="nope")
    assert unknown.json()["detail"]["code"] == "marketplace_plugin_not_found"

    terraform = (await category(db, "iac.terraform")).id
    imported = await _import(client, admin, url=OFFICIAL, ref="main", marketplace_plugin="terraform",
                             commit=MARKET_LATER, trust="official", items=[
                                 {"kind": "mcp_server", "path": "external_plugins/terraform", "name": "terraform",
                                  "category_id": terraform, "tracking_mode": "follow"}])
    assert imported.status_code == 201, imported.text
    skill = await db.get(Skill, imported.json()["imported"][0]["skill_id"])
    assert skill.kind == "mcp_server" and skill.upstream_path == "external_plugins/terraform"
    row = (await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill.id))).scalar_one()
    assert row.launch_spec["image_digest"] is None and row.launch_spec["passthrough"] == ["TFE_TOKEN"]
    assert not row.available_platform_chat and row.licence_spdx == "Apache-2.0"
    assert {entry["path"] for entry in row.files} == {".claude-plugin/plugin.json", ".mcp.json", "LICENSE"}
    content = content_of(row, await bundle_files(db, row.files))
    content.launch_spec = {**row.launch_spec, "server": "other"}
    with pytest.raises(SkillCatalogError) as mismatch:
        await write_content(db, skill, row, content)
    assert mismatch.value.code == "skill_mcp_launch_spec_invalid"


@pytest.mark.asyncio
async def test_a_community_skill_lists_its_script_and_the_ignored_plugin_components(client, db, fake_git):
    admin = await make_user(db, admin=True)
    body = (await _inspect(client, admin, url=COMMUNITY, ref="main", path="plugins/kubernetes-operations")).json()
    helm = body["skills"][0]
    assert helm["name"] == "helm-chart-scaffolding" and helm["scripts"] == ["scripts/validate-chart.sh"]
    assert helm["licence"]["spdx"] == "MIT" and helm["files"] == 4
    assert {item["path"] for item in body["ignored"]} == {"plugins/kubernetes-operations/agents",
                                                          "plugins/kubernetes-operations/hooks"}
    helm_category = (await category(db, "kubernetes.helm")).id
    imported = await _import(client, admin, url=COMMUNITY, ref="main", commit=body["commit"],
                             items=[{"path": helm["path"], "category_id": helm_category}])
    row = (await db.execute(select(SkillVersion).where(
        SkillVersion.skill_id == imported.json()["imported"][0]["skill_id"]))).scalar_one()
    script = next(entry for entry in row.files if entry["path"] == "scripts/validate-chart.sh")
    assert script["kind"] == "script" and script["executable"] is True


@pytest.mark.asyncio
async def test_hosts_outside_the_allowlist_and_unsafe_urls_are_refused_before_any_fetch(client, db, fake_git):
    admin = await make_user(db, admin=True)
    for url, code in [("https://git.example.org/team/skills", "skill_source_host_not_allowed"),
                      ("http://github.com/a/b", "skill_source_url_invalid"),
                      ("https://user:pw@github.com/a/b", "skill_source_url_invalid"),
                      ("https://github.com/only-owner", "skill_source_url_invalid"),
                      ("file:///etc", "skill_source_url_invalid")]:
        response = await _inspect(client, admin, url=url)
        assert response.status_code == 422 and response.json()["detail"]["code"] == code, url
    traversal = await _inspect(client, admin, url=HASHICORP, path="../x")
    assert traversal.json()["detail"]["code"] == "skill_source_path_invalid"
    assert fake_git.calls == []
    saved = await client.put(f"{BASE}/settings", json={"allowed_hosts": ["github.com", "git.example.org"]},
                             headers=bearer(admin))
    assert saved.json()["allowed_hosts"] == ["git.example.org", "github.com"]
    reached = await _inspect(client, admin, url="https://git.example.org/team/skills")
    assert reached.json()["detail"]["code"] == "skill_source_ref_not_found"
    bad = await client.put(f"{BASE}/settings", json={"allowed_hosts": ["not a host"]}, headers=bearer(admin))
    assert bad.json()["detail"]["code"] == "skill_settings_host_invalid"


def _zip(entries: list[tuple[str, bytes, int]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


async def _upload(client, admin, name: str, data: bytes, category_id: str, tags: str = ""):
    return await client.post(f"{BASE}/import/upload", headers=bearer(admin), data={"category_id": category_id,
                                                                                  "tags": tags},
                             files={"file": (name, data, "application/octet-stream")})


@pytest.mark.asyncio
async def test_uploads_become_drafts_and_unsafe_archives_are_refused(client, db):
    admin = await make_user(db, admin=True)
    docs = (await category(db, "engineering.documentation")).id
    single = await _upload(client, admin, "SKILL.md", skill_md("doc-writer").encode(), docs, "docs, writing")
    assert single.status_code == 201, single.text
    skill = await db.get(Skill, single.json()["skill_id"])
    assert skill.name == "doc-writer" and skill.tags == ["docs", "writing"] and single.json()["version"] == 1
    duplicate = await _upload(client, admin, "SKILL.md", skill_md("doc-writer").encode(), docs)
    assert duplicate.json()["detail"] == {"code": "skill_draft_exists", "version": 1}

    archive = _zip([("release-notes/SKILL.md", skill_md("release-notes").encode(), stat.S_IFREG | 0o644),
                    ("release-notes/references/style.md", b"# Style\n", stat.S_IFREG | 0o644),
                    ("release-notes/scripts/run.sh", b"#!/bin/sh\necho hi\n", stat.S_IFREG | 0o755),
                    ("__MACOSX/release-notes/._SKILL.md", b"\x00\x01", stat.S_IFREG | 0o644)])
    zipped = await _upload(client, admin, "release-notes.zip", archive, docs)
    assert zipped.status_code == 201, zipped.text
    row = (await db.execute(select(SkillVersion).where(SkillVersion.skill_id == zipped.json()["skill_id"]))).scalar_one()
    assert [entry["path"] for entry in row.files] == ["SKILL.md", "references/style.md", "scripts/run.sh"]
    assert row.files[2]["executable"] is True and row.licence_spdx is None

    bomb = _zip([("bomb/SKILL.md", skill_md("bomb").encode() + b" " * 900_000, stat.S_IFREG | 0o644)])
    noise = base64.b64encode(os.urandom(700_000))
    mixed = _zip([("mixed/SKILL.md", skill_md("mixed").encode() + b" " * 900_000, stat.S_IFREG | 0o644),
                  ("mixed/references/noise.md", noise, stat.S_IFREG | 0o644)])
    cases = [
        ("bomb.zip", bomb, "skill_archive_ratio"),
        ("mixed.zip", mixed, "skill_archive_ratio"),
        ("link.zip", _zip([("a/SKILL.md", skill_md("a").encode(), stat.S_IFREG | 0o644),
                           ("a/evil", b"/etc/passwd", stat.S_IFLNK | 0o777)]), "skill_archive_symlink"),
        ("trav.zip", _zip([("../SKILL.md", skill_md("x").encode(), stat.S_IFREG | 0o644)]), "skill_path_traversal"),
        ("two.zip", _zip([("a/SKILL.md", skill_md("a").encode(), stat.S_IFREG | 0o644),
                          ("b/SKILL.md", skill_md("b").encode(), stat.S_IFREG | 0o644)]), "skill_archive_skill_count"),
        ("out.zip", _zip([("a/SKILL.md", skill_md("a").encode(), stat.S_IFREG | 0o644),
                          ("other.md", b"x", stat.S_IFREG | 0o644)]), "skill_archive_outside_folder"),
        ("bin.zip", _zip([("a/SKILL.md", skill_md("a").encode(), stat.S_IFREG | 0o644),
                          ("a/logo.png", b"\x89PNG\x00\x00", stat.S_IFREG | 0o644)]), "skill_file_binary"),
        ("bad.zip", b"PK\x03\x04garbage", "skill_archive_invalid"),
        ("SKILL.md", b"no frontmatter", "skill_spec_invalid"),
        ("SKILL.md", skill_md("Bad Name").encode(), "skill_spec_invalid"),
    ]
    for name, data, code in cases:
        response = await _upload(client, admin, name, data, docs)
        assert response.status_code in {409, 422} and response.json()["detail"]["code"] == code, (name, response.text)
    too_big = await _upload(client, admin, "SKILL.md", b"x" * 5_000_001, docs)
    assert too_big.json()["detail"]["code"] == "skill_upload_too_large"
