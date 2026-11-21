"""The ``phase`` part of the run contract (``contract``): the current phase's rights, facts and notes as data."""

from __future__ import annotations

from typing import Any

from ....models import WorkflowRun
from .device_tools import device_tool_names


def _tools(policy: dict[str, Any]) -> dict[str, Any]:
    """The phase's policy names (``allow`` / ``deny``, read by the gates) and the names the device calls."""
    allow, deny = list(policy.get("allowlist") or []), list(policy.get("denylist") or [])
    return {"on_device": device_tool_names(allow, deny), "on_device_note": _text("device_tools_note"),
            "allow": allow, "deny": deny}


def _text(name: str, **values: object) -> str:
    """A note of the run contract from the catalog (``run.contract.<name>``)."""
    from ..run_texts import run_text

    return run_text(f"contract.{name}", **values)


def _refresh_device_tools(contract: dict[str, Any]) -> None:
    """Re-derive ``on_device`` after the agent / fail-closed narrowing changed ``allow`` / ``deny``."""
    tools = (contract.get("phase") or {}).get("tools")
    if isinstance(tools, dict):
        contract["phase"]["tools"] = _tools({"allowlist": tools.get("allow"), "denylist": tools.get("deny")})


def _phase(run: WorkflowRun, node: Any, *, browser: bool = False, research: int | None = None) -> dict[str, Any]:
    """``browser``: the phase has a browser of its own (``browser.phase_allows_browser``, decided by the caller);
    ``research``: the Workspace lists the phase for web research, with this many sources (``research``)."""
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
        # The recorded artefacts the phase consumes, and the one it must submit (``phase_outputs``).
        "inputs": dict(phase_facts.get("inputs") or {}),
        "output": phase_facts.get("output"),
        # The results the phase ends with (one recorded with its tool), when it declares them.
        **({"result": phase_facts["result"]} if phase_facts.get("result") else {}),
        **_phase_notes(node, policy, phase_facts, contract, browser=browser),
        "web_requests": _text("web_requests"),
    }


def _carried_facts(phase_facts: dict[str, Any]) -> dict[str, Any]:
    """The facts carried back to the phase, each only when the run recorded it."""
    return {
        # A red pipeline's resume tells the session to read phase.pipeline_failure, so the contract carries it;
        # without it the session finds nothing and changes nothing.
        **({"pipeline_failure": phase_facts["pipeline_failure"]} if phase_facts.get("pipeline_failure") else {}),
        # The same for a red hands-on test: without it the loop sends the run back to implement, the session finds no
        # failed scenario here and changes nothing (hands_on_unchanged).
        **({"hands_on_failure": phase_facts["hands_on_failure"]} if phase_facts.get("hands_on_failure") else {}),
        # Ticket delivery: the product owner's decisions on the review, and the assumptions they answer.
        **({"product_owner_answers": list(phase_facts["product_owner_answers"]),
            "review_assumptions": list(phase_facts.get("review_assumptions") or [])}
           if phase_facts.get("product_owner_answers") else {}),
        # A follow-up pass starts from its own change instead of re-reading the repository (``previous_change``).
        **({"previous_change": dict(phase_facts["previous_change"])} if phase_facts.get("previous_change") else {}),
        # The readiness check's task list: the agreed work, item by item, each with its proof test (``task_list``).
        **({"task_list": list(phase_facts["task_list"]), "task_list_rule": phase_facts.get("task_list_rule")}
           if phase_facts.get("task_list") else {}),
    }


def _phase_notes(node: Any, policy: dict[str, Any], phase_facts: dict[str, Any], contract: dict[str, Any], *,
                 browser: bool) -> dict[str, Any]:
    """The phase's notes on tests, the browser, knowledge, research and its shell, each only where it applies."""
    from .browser import BROWSER_NOTE
    from .research import RESEARCH_KEY
    from .shell_rules import SHELL_FREE, SHELL_STRICT

    return {
        # the device agent looked for run_test_suite, tried `pytest --version` (refused) and gave up.
        # ``run_contract`` words it for the repository's declared environment (``how_to_run_tests``).
        **({"how_to_run_tests": how_to_run_tests(None)} if "run_test_suite" in set(policy.get("allowlist") or [])
           and "run_test_suite" not in set(policy.get("denylist") or []) else {}),
        # Told only "fail on an assertion, change only test files", the
        # agent stubbed the class under test inside the test file; the protected tests then kept the stub forever.
        **({"how_to_write_new_tests": _text("new_tests")} if _writes_or_plans_tests(node.config, phase_facts)
           else {}),
        # the story session looks at its screens in Chrome itself (``browser``, opt-in per node or
        # per Workspace, ``device_runs.browser_phases``).
        **({"browser": dict(BROWSER_NOTE)} if browser else {}),
        # Knowledge-first over web search: every phase that may search the Workspace's knowledge is
        # instructed to query Workspace knowledge (and code) before falling back to web search.
        **({"knowledge_first": _text("knowledge_first")}
           if "knowledge_search" in set(policy.get("allowlist") or []) else {}),
        # a phase the Workspace lists researches on the web first (``research``).
        **({"research": dict(contract[RESEARCH_KEY])} if contract.get(RESEARCH_KEY) else {}),
        # epic-delivery: the story session's shell is free like plain Claude Code's (``shell_rules.free_shell``).
        # The team's strict shell for this node (``shell: strict``).
        **({"shell": dict(node.config or {})["shell"]}
           if dict(node.config or {}).get("shell") in (SHELL_FREE, SHELL_STRICT) else {}),
    }


# Inside Claude Code's macOS sandbox curl and Python fail the HTTPS certificate check
# for hosts whose chain the macOS trust evaluation completes outside the sandbox (example.com: an SSL.com root
# cross-signed by AAA); Node goes through the sandbox's proxy (the launcher sets NODE_USE_ENV_PROXY) and verifies with
# its own CAs.


def _writes_or_plans_tests(config: dict[str, Any], phase_facts: dict[str, Any]) -> bool:
    """A phase that writes the tests (its write patterns are test paths) or proposes the test contract."""
    from ..path_rules import phase_write_patterns

    output = phase_facts.get("output")
    kind = str(output.get("kind") if isinstance(output, dict) else output or "")
    patterns = [str(pattern) for pattern in phase_write_patterns(config) or []]
    return kind == "test_contract" or (bool(patterns) and all("test" in pattern.lower() for pattern in patterns))


def how_to_run_tests(environment: Any) -> str:
    """How the phase runs its tests on the device (``phase.how_to_run_tests``): the catalog's ``run.tests.*`` wording
    with the runner of the repository's declared command (stack data: ``stacks.json`` ``test_runner.hint``), the
    environment file's test entry, or every stack's runner when nothing is declared. A fixed
    pytest text would be wrong in a Flutter repository."""
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
    # Without the hint an agent spent 15 calls looking for a red Flutter test's message in the short output.
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
