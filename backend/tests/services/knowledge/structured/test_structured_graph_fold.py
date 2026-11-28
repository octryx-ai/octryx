"""A difference between placeholder definitions is reported once, on the settings resolving from them."""

from __future__ import annotations

import pytest

from app.services.knowledge.access.authorization import authorize_workspace
from app.services.knowledge.structured.build import claim_next_build, request_build
from app.services.knowledge.structured.build_slice import run_build_slice
from app.services.knowledge.structured.build_states import TRIGGER_MANUAL
from app.services.knowledge.structured.config_families import Placeholders
from app.services.knowledge.structured.config_linkage_compute import compute_linkage
from app.services.knowledge.structured.config_report import handbook_vs_reality
from app.services.knowledge.structured.profile import PROFILE_PATH, load_profile
from app.services.knowledge.structured.profile import structured_profile as profile
from app.services.knowledge.structured.profile_types import StructuredProfileError
from tests.knowledge_evidence_runtime_support import build_runtime
from tests.knowledge_evidence_seed_support import fetch_user, seed_member, seed_workspace
from tests.knowledge_runtime_support import set_evidence_runtime
from tests.services.knowledge.structured.structured_graph_support import (
    SERVER_MANUAL,
    seed_config_repository,
    seed_parsed_revision,
)
from tests.services.knowledge.structured.test_structured_graph_noise import DOCUMENTS, PARAMETERS, _setting


def _inconsistencies(settings, *, fold: bool) -> list:
    placeholders = Placeholders(settings, profile().placeholder_pattern, profile().placeholder_sources)
    edges = compute_linkage(settings, PARAMETERS, DOCUMENTS, profile().registry_sections, placeholders,
                            profile().non_comparable_defaults, fold)
    return [edge for edge in edges if edge.edge_type == "inconsistent_across"]


CONF_DEF = _setting("conf/shop_config.properties", None, "Conf_Threads", "4", 3, documented=False)
DATA_DEF = _setting("data/shop_config.properties", None, "Conf_Threads", "8", 3, documented=False)
CONF_INI = _setting("conf/app.ini", "Cache1", "PoolSize", "${Conf_Threads}", 5)
DATA_INI = _setting("data/app.ini", "Cache1", "PoolSize", "${Conf_Threads}", 5)


def _pair(edge) -> set[str]:
    return {edge.source_id, edge.target_id}


def test_a_definition_difference_is_folded_into_the_settings_that_resolve_from_it():
    settings = [CONF_DEF, DATA_DEF, CONF_INI, DATA_INI]
    (edge,) = _inconsistencies(settings, fold=True)
    assert _pair(edge) == {CONF_INI.node_id, DATA_INI.node_id} and sorted(edge.properties["values"]) == ["4", "8"]
    # The settings' edge cites the definition lines it rests on.
    assert {CONF_DEF.cite, DATA_DEF.cite} <= set(edge.citations)
    unfolded = _inconsistencies(settings, fold=False)
    assert sorted(map(frozenset, map(_pair, unfolded)), key=sorted) == sorted(
        [frozenset({CONF_INI.node_id, DATA_INI.node_id}), frozenset({CONF_DEF.node_id, DATA_DEF.node_id})], key=sorted)


def test_a_definition_difference_no_differing_settings_pair_resolves_from_is_still_reported():
    # No setting uses the definitions.
    (alone,) = _inconsistencies([CONF_DEF, DATA_DEF], fold=True)
    assert _pair(alone) == {CONF_DEF.node_id, DATA_DEF.node_id}
    # Only one side resolves from a definition: the settings differ, but not "from exactly those two".
    literal = _setting("data/app.ini", "Cache1", "PoolSize", "8", 5)
    pairs = {frozenset(_pair(edge)) for edge in _inconsistencies([CONF_DEF, DATA_DEF, CONF_INI, literal], fold=True)}
    assert pairs == {frozenset({CONF_INI.node_id, literal.node_id}), frozenset({CONF_DEF.node_id, DATA_DEF.node_id})}
    # The settings resolve to the same value: nothing reports the definitions' difference, so they keep it.
    same = _setting("data/app.ini", "Cache1", "PoolSize", "4", 5)
    (kept,) = _inconsistencies([CONF_DEF, DATA_DEF, CONF_INI, same], fold=True)
    assert _pair(kept) == {CONF_DEF.node_id, DATA_DEF.node_id}


def test_only_differing_settings_fold_a_definition_pair_never_a_definition_chain():
    # Conf_Threads resolves from Base_Threads in both components; no setting uses Conf_Threads.
    base_conf = _setting("conf/shop_config.properties", None, "Base_Threads", "4", 1, documented=False)
    base_data = _setting("data/shop_config.properties", None, "Base_Threads", "8", 1, documented=False)
    chain_conf = _setting("conf/shop_config.properties", None, "Conf_Threads", "${Base_Threads}", 3, documented=False)
    chain_data = _setting("data/shop_config.properties", None, "Conf_Threads", "${Base_Threads}", 3, documented=False)
    pairs = {frozenset(_pair(edge)) for edge in _inconsistencies([base_conf, base_data, chain_conf, chain_data],
                                                                 fold=True)}
    assert pairs == {frozenset({base_conf.node_id, base_data.node_id}), frozenset({chain_conf.node_id, chain_data.node_id})}


def test_two_ordinary_settings_are_never_folded():
    left = _setting("conf/app.ini", "Cache1", "RequestTimeout", "500", 2)
    right = _setting("data/app.ini", "Cache1", "RequestTimeout", "60000", 2)
    (edge,) = _inconsistencies([left, right], fold=True)
    assert _pair(edge) == {left.node_id, right.node_id}


def test_the_switch_is_on_by_default_and_must_be_a_boolean(tmp_path):
    assert profile().fold_resolved_definitions is True
    raw = PROFILE_PATH.read_text(encoding="utf-8")
    broken = tmp_path / "structured.json"
    broken.write_text(raw.replace('"fold_resolved_definitions": true', '"fold_resolved_definitions": "yes"'),
                      encoding="utf-8")
    with pytest.raises(StructuredProfileError, match="fold_resolved_definitions"):
        load_profile(broken)


FILES = {
    "conf/app.ini": "[Cache1]\nPoolSize = ${Conf_Threads}\n",
    "conf/shop_config.properties": "Conf_Threads=4\n",
    "data/app.ini": "[Cache1]\nPoolSize = ${Conf_Threads}\n",
    "data/shop_config.properties": "Conf_Threads=8\n",
}


async def test_the_report_lists_the_difference_once_through_a_real_build(db):
    project_id = await seed_workspace(db, name="Fold")
    user = await fetch_user(db, await seed_member(db, workspace_id=project_id, role="admin"))
    authorized = await authorize_workspace(db, current_user=user, workspace_id=project_id)
    runtime, _, evidence_index = build_runtime()
    set_evidence_runtime(runtime)
    await seed_parsed_revision(db, project_id, source_key="server-manual", title="Server Manual", spans=SERVER_MANUAL)
    await seed_config_repository(db, runtime, authorized, connector_key="repo-ini", repo="ini", files=FILES)
    build = await request_build(db, project_id=project_id, layers=["manual", "configuration"], trigger=TRIGGER_MANUAL)
    await claim_next_build(db, worker_id="w")
    assert await run_build_slice(db, runtime=runtime, build_id=build.id, worker_id="w") == "completed"
    report = await handbook_vs_reality(db, authorized=authorized)
    assert report["counts"]["inconsistencies"] == 1
    (item,) = report["inconsistencies"]
    assert {value["file"] for value in item["values"]} == {"conf/app.ini", "data/app.ini"}
