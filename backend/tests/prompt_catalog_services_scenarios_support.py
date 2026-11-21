"""Fixed inputs for the services prompt-builder golden scenarios (analysis, delegation, secure work, tool guards).

``scenario_outputs`` runs the catalog-backed builders with these inputs; every builder must produce the pinned
digests of ``prompt_catalog_services_scenarios.py``.
The secure work and tool guard groups live in ``prompt_catalog_services_guard_scenarios_support``.
"""

from __future__ import annotations

from hashlib import sha256

from tests.prompt_catalog_services_guard_scenarios_support import _secure_work, _tool_guard


def _analysis() -> dict[str, str]:
    from app.services.request_analysis.contract import build_request_analysis_contract_message

    return {
        "analysis:contract:plain": build_request_analysis_contract_message(
            {"required_domains": ["jira", "confluence"], "language_contract": {"output_language": "de"}}
        ),
        "analysis:contract:empty": build_request_analysis_contract_message({}),
    }


def _delegation() -> dict[str, str]:
    from app.services.coordinator_control import _continue_prompt_for_contract
    from app.tools.sub_agent import _build_bounded_child_agent_definition, _build_child_task

    outputs: dict[str, str] = {}
    resolution = {
        "prompt_contract": {"intent": "migrate", "stack_key": "java-spring", "target_versions": {"java": "25"}},
        "repository": {"name": "proxy", "repo_root": "/r"},
        "engineering_knowledge_pack": {"pack_key": "p", "version": 2, "quality_status": "passed"},
    }
    outputs["child:task:plain"] = _build_child_task("Do X", parent_request="P", engineering_resolution={})
    outputs["child:task:migration"] = _build_child_task("Do X", parent_request=" Upgrade it ", engineering_resolution=resolution)
    outputs["child:task:no_parent"] = _build_child_task("Do X", parent_request=None, engineering_resolution=resolution)
    for name, kwargs in {
        "coding": {"child_agent_type": "coding", "allowed_tools": ["read_file"]},
        "research_one": {"child_agent_type": "documentation", "allowed_tools": ["web_search", "ingest_document_source"]},
        "research_many": {"child_agent_type": "documentation", "allowed_tools": ["web_search"], "min_sources_per_child": 3},
        "research_no_search": {"child_agent_type": "documentation", "allowed_tools": ["ingest_document_source"]},
    }.items():
        outputs[f"child:definition:{name}"] = repr(_build_bounded_child_agent_definition(**kwargs))

    class _Contract:
        def __init__(self, mode: str) -> None:
            self.coordinator_mode = mode

    for mode in ("worker_delegation", "direct"):
        outputs[f"coordinator:{mode}"] = _continue_prompt_for_contract(_Contract(mode))
    return outputs


SCENARIO_GROUPS = [_analysis, _delegation, _secure_work, _tool_guard]


def scenario_outputs() -> dict[str, str]:
    outputs: dict[str, str] = {}
    for group in SCENARIO_GROUPS:
        outputs.update(group())
    return outputs


def scenario_digests() -> dict[str, str]:
    from tests.prompt_catalog_knowledge_scenarios_support import pinned_fence

    with pinned_fence():
        outputs = scenario_outputs()
    return {name: sha256(text.encode("utf-8")).hexdigest() for name, text in outputs.items()}
