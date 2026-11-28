"""The ``phase`` part of the run contract (``contract``): the current phase's rights, facts and notes as data."""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from .device_tools import device_tool_names


def _tools(policy: dict[str, Any]) -> dict[str, Any]:
    allow, deny = list(policy.get("allowlist") or []), list(policy.get("denylist") or [])
    return {"on_device": device_tool_names(allow, deny), "on_device_note": _text("device_tools_note"),
            "allow": allow, "deny": deny}


def _text(name: str, **values: object) -> str:
    from ..run_texts import run_text

    return run_text(f"contract.{name}", **values)


def _refresh_device_tools(contract: dict[str, Any]) -> None:
    tools = (contract.get("phase") or {}).get("tools")
    if isinstance(tools, dict):
        contract["phase"]["tools"] = _tools({"allowlist": tools.get("allow"), "denylist": tools.get("deny")})


def _phase(run: WorkflowRun, node: Any, *, browser: bool = False, research: int | None = None) -> dict[str, Any]:
    from ..path_rules import phase_create_patterns, phase_write_patterns, protects_confirmed_tests, writes_tests
    from ..phase_contract import phase_definition
    from .research import with_research

    definition = with_research(phase_definition(run, node), research)
    contract = dict(definition.get("workflow_contract") or {})
    policy = dict(definition.get("tool_policy") or {})
    from ..test_runs import confirmed_by

    files = dict(dict(run.context or {}).get("confirmed_test_files") or {})
    phase_facts = dict(contract.get("workflow_run_phase") or {})
    return {
        "node_id": node.id, "title": node.title,
        "capability_class": str(contract.get("capability_class") or "read_only"),
        "tools": _tools(policy),
        "path_rules": {"write": phase_write_patterns(node.config), "create": phase_create_patterns(node.config),
                       "protect_confirmed_tests": protects_confirmed_tests(node.config),
                       "write_tests": writes_tests(node.config)},
        # The run's environment file is its contract (``workspace.contract_pin``): only a node that allows it edits it.
        "contract_file": str(dict(dict(run.context or {}).get("contract_pin") or {}).get("file") or ""),
        "allow_contract_change": dict(node.config or {}).get("allow_contract_change") is True,
        "protected_by": confirmed_by(run),
        "protected_files": sorted({str(entry.get("file")) for entry in files.values()
                                   if isinstance(entry, dict) and entry.get("file")}),
        "checks": [str(check.get("description") or check.get("type") or "") for check in contract.get("checks") or []
                   if isinstance(check, dict)],
        "when_to_use": str(contract.get("when_to_use") or ""),
        "findings": list(phase_facts.get("findings") or []),
        "review_findings": list(phase_facts.get("review_findings") or []),
        **_carried_facts(phase_facts),
        "inputs": dict(phase_facts.get("inputs") or {}),
        "output": phase_facts.get("output"),
        **({"result": phase_facts["result"]} if phase_facts.get("result") else {}),
        **_phase_notes(node, policy, phase_facts, contract, browser=browser),
        "web_requests": _text("web_requests"),
    }


def _carried_facts(phase_facts: dict[str, Any]) -> dict[str, Any]:
    return {
        # A red pipeline's resume tells the session to read phase.pipeline_failure, so the contract must carry it.
        **({"pipeline_failure": phase_facts["pipeline_failure"]} if phase_facts.get("pipeline_failure") else {}),
        **({"hands_on_failure": phase_facts["hands_on_failure"]} if phase_facts.get("hands_on_failure") else {}),
        **({"product_owner_answers": list(phase_facts["product_owner_answers"]),
            "review_assumptions": list(phase_facts.get("review_assumptions") or [])}
           if phase_facts.get("product_owner_answers") else {}),
        **({"previous_change": dict(phase_facts["previous_change"])} if phase_facts.get("previous_change") else {}),
        **({"task_list": list(phase_facts["task_list"]), "task_list_rule": phase_facts.get("task_list_rule")}
           if phase_facts.get("task_list") else {}),
    }


def _phase_notes(node: Any, policy: dict[str, Any], phase_facts: dict[str, Any], contract: dict[str, Any], *,
                 browser: bool) -> dict[str, Any]:
    from .browser import BROWSER_NOTE
    from .research import RESEARCH_KEY
    from .shell_rules import SHELL_FREE, SHELL_STRICT

    return {
        **({"how_to_run_tests": how_to_run_tests(None)} if "run_test_suite" in set(policy.get("allowlist") or [])
           and "run_test_suite" not in set(policy.get("denylist") or []) else {}),
        # Told only to fail on an assertion, an agent stubs the class under test inside the test file.
        **({"how_to_write_new_tests": _text("new_tests")} if _writes_or_plans_tests(node.config, phase_facts)
           else {}),
        **({"browser": dict(BROWSER_NOTE)} if browser else {}),
        **({"knowledge_first": _text("knowledge_first")}
           if "knowledge_search" in set(policy.get("allowlist") or []) else {}),
        **({"research": dict(contract[RESEARCH_KEY])} if contract.get(RESEARCH_KEY) else {}),
        **({"shell": dict(node.config or {})["shell"]}
           if dict(node.config or {}).get("shell") in (SHELL_FREE, SHELL_STRICT) else {}),
    }


# Inside Claude Code's macOS sandbox curl and Python fail the certificate check for some chains; Node goes through
# the sandbox's proxy and verifies with its own CAs.


def _writes_or_plans_tests(config: dict[str, Any], phase_facts: dict[str, Any]) -> bool:
    from ..path_rules import phase_write_patterns

    output = phase_facts.get("output")
    kind = str(output.get("kind") if isinstance(output, dict) else output or "")
    patterns = [str(pattern) for pattern in phase_write_patterns(config) or []]
    return kind == "test_contract" or (bool(patterns) and all("test" in pattern.lower() for pattern in patterns))


def how_to_run_tests(environment: Any) -> str:
    from ...engineering_knowledge.stacks import test_runners
    from ..run_texts import run_text

    environment = dict(environment or {}) if isinstance(environment, dict) else {}
    runners = test_runners()
    declared = str(environment.get("test") or "").strip()
    words = declared.replace(";", " ").split()

    def runs(runner: dict[str, Any]) -> bool:
        return any(words[index:index + len(command)] == list(command) for command in runner.get("commands") or []
                   for index in range(len(words)))

    matched = next((runner for runner in runners if declared and runs(runner)), None)
    failing = f"; {matched['failure_hint']}" if matched and matched.get("failure_hint") else ""
    hint = f" ({matched['hint']}{failing})" if matched and matched.get("hint") else ""
    if declared:
        how = run_text("tests.declared", command=declared, hint=hint)
    elif environment.get("environment_file"):
        how = run_text("tests.environment_file", file=environment["environment_file"], hint="")
    else:
        how = run_text("tests.undeclared", hints="; ".join(f"{runner.get('label') or 'tests'}: {runner['hint']}"
                                                           for runner in runners if runner.get("hint")))
    return run_text("tests.how", how=how)
