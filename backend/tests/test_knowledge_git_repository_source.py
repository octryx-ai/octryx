"""Source Sync ``git_repository`` (``remote_git``): a public repository at a commit feeds Knowledge.

Contract tests against a fake GitHub (``httpx.MockTransport`` behind the real pinned egress
transport, no network), injected the way the Jira and Confluence tests inject theirs:

- a branch ref resolves to a sha once; every file is one revision whose link is the blob at that sha;
  binary, too-large, excluded and empty files are skipped with their closed outcome, and the
  commit is recorded (run report ``repository.commit``, scope ``head_commit``);
- a re-sync of the same sha is ``unchanged`` everywhere and creates no revision;
- a retrieved code span links ``blob/<sha>/<path>#L<start>-L<end>`` and carries its lines;
- a host that resolves to a private address is refused (``egress_refused``) before anything is sent;
- ``knowledge_code_impact``'s resolver reads the Workspace repository at its head commit, with blob
  links per location; several repositories are ``needs_clarification``, none ``needs_configuration``;
- the configuration is closed (https, a known host, a valid ref, no other kind's fields).
"""

from __future__ import annotations

import io
import ipaddress
import tarfile

import httpx
import pytest
from sqlalchemy import func, select

from app.models.project.knowledge_evidence import KnowledgeSourceRevision, KnowledgeSourceRevisionOrigin
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.code.codebase import (
    CODEBASE_WORKSPACE_REPOSITORY,
    STATE_NEEDS_CLARIFICATION,
    STATE_NEEDS_CONFIGURATION,
    Codebase,
    CodebaseRefusal,
    resolve_codebase,
)
from app.services.knowledge.code.repository_reads import load_repository_index
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.projection.projector import EvidenceProjector
from app.services.knowledge.retrieval.evidence import retrieve_workspace_evidence
from app.services.knowledge.retrieval.locator import evidence_locator
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.service import configure_connector
from app.services.knowledge.sources.sync.service_run import run_connector
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace

OWNER, REPO = "spring-projects", "spring-petclinic"
SHA = "b26f235250627a235a2974a22f2317dbef27338d"
NEXT_SHA = "c" * 40
OWNER_JAVA = "src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java"
JAVA = """package org.springframework.samples.petclinic.owner;

import org.springframework.stereotype.Controller;

@Controller
class OwnerController {

    /** Shows the creation form. */
    @GetMapping("/owners/new")
    public String initCreationForm() {
        return "owners/createOrUpdateOwnerForm";
    }
}
"""
POM = """<project>
  <properties>
    <java.version>17</java.version>
  </properties>
  <dependencies>
    <dependency><artifactId>spring-boot-starter-web</artifactId></dependency>
  </dependencies>
</project>
"""
FILES = {
    OWNER_JAVA: JAVA.encode(),
    "pom.xml": POM.encode(),
    "README.md": b"# Petclinic\n\nA sample application.\n",
    "src/main/resources/static/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
    "src/main/resources/db/big.sql": b"insert into t values (1);\n" * 400,
    "docs/notes.txt": b"Excluded by the glob.\n",
    "empty.txt": b"   \n",
}


def _tarball(files: dict[str, bytes], sha: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        top = tarfile.TarInfo(f"{REPO}-{sha}")
        top.type = tarfile.DIRTYPE
        tar.addfile(top)
        for path, data in sorted(files.items()):
            info = tarfile.TarInfo(f"{REPO}-{sha}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FakeGitHub:
    """``GET`` the commit a ref names (``application/vnd.github.sha``) and the archive at a sha."""

    def __init__(self) -> None:
        self.refs = {"main": SHA}
        self.trees = {SHA: dict(FILES)}
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and "authorization" not in request.headers
        self.requests.append(str(request.url))
        host, path = request.url.host, request.url.path
        if host == "api.github.com" and path.startswith(f"/repos/{OWNER}/{REPO}/commits/"):
            assert request.headers["accept"] == "application/vnd.github.sha"
            sha = self.refs.get(path.rsplit("/", 1)[-1])
            return httpx.Response(200, text=sha) if sha else httpx.Response(404)
        if host == "codeload.github.com" and path.startswith(f"/{OWNER}/{REPO}/tar.gz/"):
            sha = path.rsplit("/", 1)[-1]
            return httpx.Response(200, content=_tarball(self.trees[sha], sha)) if sha in self.trees else httpx.Response(404)
        return httpx.Response(404)


@pytest.fixture
def dns(monkeypatch):
    """GitHub resolves publicly unless a test makes it private."""
    state = {"address": "203.0.113.10"}

    async def _resolve(hostname: str, port: int | None):
        return {ipaddress.ip_address(state["address"])}

    async def _no_allowlist(connection: str) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr("app.services.outbound_url_policy._resolve_hostname_ips", _resolve)
    monkeypatch.setattr("app.services.outbound_egress.target_check._private_host_keys", _no_allowlist)
    return state


def _config(key: str = "petclinic", **overrides):
    values = {
        "repository_url": f"https://github.com/{OWNER}/{REPO}",
        "ref": "main",
        "exclude_globs": ["docs/**"],
        "max_file_bytes": 4096,
        "fetch_mode": "remote_git",
    }
    values.update(overrides)
    return validate_config(connector_key=key, kind="git_repository", **values)


async def _setup(db, *, keys: tuple[str, ...] = ("petclinic",)):
    workspace_id = await seed_workspace(db)
    user_id = await seed_member(db, workspace_id=workspace_id, role="admin")
    authorized = await authorize_workspace(db, current_user=await fetch_user(db, user_id), workspace_id=workspace_id)
    runtime, _, evidence_index = build_runtime()
    rows = [await configure_connector(db, authorized=authorized, config=_config(key), actor_id=user_id) for key in keys]
    return authorized, user_id, runtime, rows


async def _run(db, setup, github: FakeGitHub, row=None):
    authorized, user_id, runtime, rows = setup
    row = await db.get(KnowledgeSourceConnector, (row or rows[0]).id)
    transport = httpx.MockTransport(github.handler)
    return await run_connector(db, runtime=runtime, authorized=authorized, row=row, actor_id=user_id, transport=transport)


async def _revisions(db, project_id: str) -> int:
    statement = select(func.count()).select_from(KnowledgeSourceRevision)
    return (await db.execute(statement.where(KnowledgeSourceRevision.project_id == project_id))).scalar_one()


async def _drain(db, runtime) -> None:
    projector = EvidenceProjector(runtime)
    for _ in range(40):
        if await projector.project_once(db, worker_id="test") is None:
            return
    raise AssertionError("the outbox did not drain")


async def test_a_branch_is_ingested_at_its_sha_with_closed_file_outcomes(db, dns) -> None:
    setup = await _setup(db)
    github = FakeGitHub()

    run = await _run(db, setup, github)

    assert run.state == "completed" and run.reason is None
    assert run.report["created"] == 3 and run.report["failed"] == 0
    assert run.report["skipped_reasons"] == {
        "excluded": 1,
        "skipped_binary": 1,
        "skipped_empty": 1,
        "skipped_too_large": 1,
    }
    assert run.report["repository"] == {"ref": "main", "commit": SHA}
    row = await db.get(KnowledgeSourceConnector, setup[3][0].id)
    assert row.scope["head_commit"] == SHA and row.scope["head_dirty"] is False
    origins = sorted((await db.execute(select(KnowledgeSourceRevisionOrigin.source_url))).scalars())
    blob = f"https://github.com/{OWNER}/{REPO}/blob/{SHA}"
    assert origins == [f"{blob}/README.md", f"{blob}/pom.xml", f"{blob}/{OWNER_JAVA}"]
    # The ref resolved once; nothing but the commit lookup and one archive was requested.
    assert len(github.requests) == 2 and github.requests[0].endswith("/commits/main")


async def test_a_resync_of_the_same_sha_is_unchanged_and_creates_no_revision(db, dns) -> None:
    setup = await _setup(db)
    github = FakeGitHub()
    await _run(db, setup, github)

    again = await _run(db, setup, github)

    assert again.state == "completed"
    assert {key: again.report[key] for key in ("created", "updated", "unchanged", "retired", "failed")} == {
        "created": 0,
        "updated": 0,
        "unchanged": 3,
        "retired": 0,
        "failed": 0,
    }
    assert await _revisions(db, setup[0].project_id) == 3


async def test_a_code_span_links_its_blob_at_the_sha_with_a_line_anchor(db, dns) -> None:
    setup = await _setup(db)
    authorized, _, runtime, _ = setup
    await _run(db, setup, FakeGitHub())
    await _drain(db, runtime)

    result = await retrieve_workspace_evidence(db, runtime=runtime, authorized=authorized, query_text="initCreationForm")

    hit = next(item for item in result.evidence if "initCreationForm" in item.text)
    # The class header and its method are one span (A3-green); the hit quotes exactly those lines,
    # never the retrieval text the projection indexed it by.
    assert hit.text == "\n".join(JAVA.split("\n")[4:12])
    assert hit.source_url == f"https://github.com/{OWNER}/{REPO}/blob/{SHA}/{OWNER_JAVA}#L5-L12"
    assert (hit.line_start, hit.line_end) == (5, 12) and hit.section_path == ("OwnerController",)
    locator = evidence_locator(hit)
    assert locator["lines"] == [5, 12] and locator["kind"] == "code"
    # The repository names the file, and a code span names its lines.
    assert locator["cite_as"] == f"[{REPO}:{OWNER_JAVA} § OwnerController L5-12]({hit.source_url})"
    assert "(rev 1, lines 5-12, § OwnerController)" in hit.citation


async def test_a_host_on_a_private_address_is_refused_before_anything_is_sent(db, dns) -> None:
    setup = await _setup(db)
    github = FakeGitHub()
    dns["address"] = "10.0.0.5"

    run = await _run(db, setup, github)

    assert run.state == "failed" and run.reason == "egress_refused"
    assert github.requests == [] and await _revisions(db, setup[0].project_id) == 0
    assert run.report["repository"] == {"ref": "main", "commit": None}


async def test_code_impact_resolves_the_workspace_repository_at_its_head_commit(db, dns) -> None:
    setup = await _setup(db)
    authorized = setup[0]
    before = await resolve_codebase(db, project_id=authorized.project_id)
    assert isinstance(before, CodebaseRefusal) and before.reason == "repository_not_synced"
    await _run(db, setup, FakeGitHub())

    codebase = await resolve_codebase(db, project_id=authorized.project_id)

    assert isinstance(codebase, Codebase) and codebase.kind == CODEBASE_WORKSPACE_REPOSITORY
    assert codebase.commit == SHA and codebase.repository.connector_key == "petclinic"
    index = await load_repository_index(db, connector_id=codebase.repository.connector_id, head_commit=SHA)
    values = {(element.kind, element.value, element.path) for element in index.elements}
    assert ("import", "org.springframework.stereotype.Controller", OWNER_JAVA) in values
    assert ("dependency", "spring-boot-starter-web", "pom.xml") in values
    assert codebase.repository.blob_link("pom.xml", 3) == f"https://github.com/{OWNER}/{REPO}/blob/{SHA}/pom.xml#L3"


async def test_several_repositories_need_clarification_and_none_need_configuration(db, dns) -> None:
    setup = await _setup(db, keys=("petclinic", "realworld"))
    authorized = setup[0]

    several = await resolve_codebase(db, project_id=authorized.project_id)
    chosen = await resolve_codebase(db, project_id=authorized.project_id, repository="realworld")
    unknown = await resolve_codebase(db, project_id=authorized.project_id, repository="nope")
    empty = await resolve_codebase(db, project_id=await seed_workspace(db))

    assert isinstance(several, CodebaseRefusal) and several.state == STATE_NEEDS_CLARIFICATION
    assert [candidate["repository"] for candidate in several.candidates] == ["petclinic", "realworld"]
    assert isinstance(chosen, CodebaseRefusal) and chosen.reason == "repository_not_synced"
    assert isinstance(unknown, CodebaseRefusal) and unknown.reason == "unknown_repository"
    assert isinstance(empty, CodebaseRefusal) and empty.state == STATE_NEEDS_CONFIGURATION


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository_url": f"http://github.com/{OWNER}/{REPO}"},
        {"repository_url": f"https://gitlab.com/{OWNER}/{REPO}"},
        {"repository_url": f"https://github.com/{OWNER}/{REPO}.git"},
        {"repository_url": f"https://user:pw@github.com/{OWNER}/{REPO}"},
        {"repository_url": f"https://github.com/{OWNER}/{REPO}/tree/main"},
        {"ref": "../main"},
        {"ref": "-x"},
        {"ref": None},
        {"fetch_mode": "local_snapshot"},
        {"max_files": 0},
        {"max_file_bytes": 10},
        {"include_globs": ["/abs/**"]},
        {"exclude_globs": ["../**"]},
        {"spaces": ["ENG"]},
    ],
)
def test_the_configuration_is_closed(overrides) -> None:
    with pytest.raises(InvalidEvidenceRequestError):
        _config(**overrides)


def test_a_full_sha_ref_is_pinned_and_other_kinds_refuse_git_fields() -> None:
    config = _config(ref=SHA.upper())
    assert config.scope["ref"] == SHA and config.scope["remote"] == f"https://github.com/{OWNER}/{REPO}"
    with pytest.raises(InvalidEvidenceRequestError):
        validate_config(connector_key="ops", kind="jira", project_keys=["OPS"], ref="main")
