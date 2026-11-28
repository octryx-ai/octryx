"""Fixed inputs for the services prompt-builder golden scenarios; the secure work and tool guard groups live in
``prompt_catalog_services_guard_scenarios_support``."""

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


SCENARIO_GROUPS = [_analysis, _secure_work, _tool_guard]


def scenario_outputs() -> dict[str, str]:
    outputs: dict[str, str] = {}
    for group in SCENARIO_GROUPS:
        outputs.update(group())
    return outputs


def scenario_digests() -> dict[str, str]:
    from tests.services.prompt_catalog.prompt_catalog_knowledge_scenarios_support import pinned_fence

    with pinned_fence():
        outputs = scenario_outputs()
    return {name: sha256(text.encode("utf-8")).hexdigest() for name, text in outputs.items()}
