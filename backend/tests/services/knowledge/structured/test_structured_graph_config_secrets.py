"""No comment or continuation prefix folds a secret past the configuration layer's redaction."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models.project.knowledge_structured import KnowledgeStructuredNode
from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import TRIGGER_MANUAL
from app.services.knowledge.structured.config_files import parse_ini
from app.services.knowledge.structured.profile import default_profile_document
from app.services.knowledge.structured.profile_types import StructuredProfileError
from app.services.knowledge.structured.workspace_profile import save_workspace_profile, validate_document
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.knowledge_runtime_support import set_evidence_runtime
from tests.services.knowledge.structured.structured_graph_support import seed_config_repository


def _values(parsed) -> list[tuple[str, str, bool]]:
    return [(entry.key, entry.value, entry.redacted) for entry in parsed.entries]


def test_a_continuation_prefix_that_spells_a_secret_key_never_stores_the_secret():
    parsed = parse_ini("[db]\nuser=admin\npassword=hunter2\nPwd=s3cr3t\nhost=db1\n", ("#",), ("password=", "Pwd"))
    assert "hunter2" not in repr(_values(parsed)) and "s3cr3t" not in repr(_values(parsed))
    assert _values(parsed) == [("user", "admin", False), ("password", "[redacted]", True),
                               ("Pwd", "[redacted]", True), ("host", "db1", False)]


def test_a_continuation_line_reading_as_a_secret_setting_is_its_own_redacted_setting():
    parsed = parse_ini("[db]\nuser=admin\n+ password = hunter2\n+ tail\nurl=x\n+ y\n", (";",), ("+",))
    assert _values(parsed) == [("user", "admin", False), ("password", "[redacted]", True), ("url", "x y", False)]
    assert parsed.skipped_lines == 1  # "+ tail" has no setting left to continue
    # An ordinary continuation still joins.
    assert _values(parse_ini("[a]\nlist=one\n+ two=2\n", (";",), ("+",))) == [("list", "one two=2", False)]


@pytest.mark.parametrize("prefix", ["password=", "Pwd", "#!#!", " #", "a", "+ ", "_"])
def test_the_profile_refuses_a_comment_or_continuation_prefix_that_is_not_short_punctuation(prefix):
    document = default_profile_document()
    continuation = copy.deepcopy(document)
    continuation["configuration"]["continuation_prefixes"] = ["+", prefix]
    with pytest.raises(StructuredProfileError, match="punctuation"):
        validate_document(continuation)
    comment = copy.deepcopy(document)
    comment["configuration"]["comment_prefixes"]["ini"] = [";", prefix]
    with pytest.raises(StructuredProfileError, match="punctuation"):
        validate_document(comment)


def test_the_default_prefixes_and_short_punctuation_are_allowed():
    document = default_profile_document()
    document["configuration"]["comment_prefixes"]["ini"] = [";", "#", "\\", "//", "--;"]
    document["configuration"]["continuation_prefixes"] = ["+", "&&"]
    profile = validate_document(document)
    assert profile.continuation_prefixes == ("+", "&&") and "//" in profile.comment_prefixes["ini"]


async def test_a_file_matched_only_by_a_workspace_glob_is_masked_before_it_is_stored(db):
    project_id = await seed_workspace(db, name="Secrets")
    user = await fetch_user(db, await seed_member(db, workspace_id=project_id, role="admin"))
    authorized = await authorize_workspace(db, current_user=user, workspace_id=project_id)
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    document = default_profile_document()
    document["layers"]["configuration"]["files"].insert(0, {"glob": "*.cfg", "format": "ini",
                                                            "manual_documented": False})
    await save_workspace_profile(db, project_id, document=document, actor_id=user.id)
    # The code ingest leaves "+password=hunter2" as is (it is no key=value line to it), and "*.cfg" is
    # no default file: only the configuration layer stands between the value and the graph.
    files = {"app/db.cfg": "[db]\nuser=admin\n+password=hunter2\nconn=jdbc:oracle:thin:scott/tiger@db1:1521\n"}
    await seed_config_repository(db, runtime, authorized, connector_key="repo-cfg", repo="cfg", files=files)
    build = await request_build(db, project_id=project_id, layers=["configuration"], trigger=TRIGGER_MANUAL)
    await claim_next_build(db, worker_id="w")
    assert await run_build_slice(db, runtime=runtime, build_id=build.id, worker_id="w") == "completed"
    rows = (await db.execute(select(KnowledgeStructuredNode.label, KnowledgeStructuredNode.properties).where(
        KnowledgeStructuredNode.project_id == project_id,
        KnowledgeStructuredNode.node_type == "ConfiguredSetting"))).all()
    stored = {label: properties for label, properties in rows}
    assert set(stored) == {"[db] user", "[db] password", "[db] conn"}
    assert stored["[db] user"]["value"] == "admin"
    assert stored["[db] password"]["redacted"] is True and stored["[db] conn"]["redacted"] is True
    assert "hunter2" not in repr(rows) and "tiger" not in repr(rows)


async def test_the_configuration_layer_spans_several_slices_of_one_claim(db):
    # A manual build's second slice must not raise KeyError 'config_files': the layer memo (filled by ``select`` in
    # the first slice) is kept across slices like the plan.
    from app.services.knowledge.structured.build_slice import SliceCache

    project_id = await seed_workspace(db, name="Slices")
    user = await fetch_user(db, await seed_member(db, workspace_id=project_id, role="admin"))
    authorized = await authorize_workspace(db, current_user=user, workspace_id=project_id)
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    files = {f"c{i}/app.ini": f"[General]\nThreads={i}\n" for i in range(3)}
    await seed_config_repository(db, runtime, authorized, connector_key="repo-s", repo="s", files=files)
    build = await request_build(db, project_id=project_id, layers=["configuration"], trigger=TRIGGER_MANUAL)
    await claim_next_build(db, worker_id="w")
    cache = SliceCache(build.id)
    states = []
    while not states or states[-1] == "running":
        states.append(await run_build_slice(db, runtime=runtime, build_id=build.id, worker_id="w",
                                            max_revisions=1, cache=cache))
    assert states[-1] == "completed" and len(states) >= 3
    labels = set((await db.execute(select(KnowledgeStructuredNode.label).where(
        KnowledgeStructuredNode.project_id == project_id,
        KnowledgeStructuredNode.node_type == "ConfiguredSetting"))).scalars())
    assert len(labels) >= 1
