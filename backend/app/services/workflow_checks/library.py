"""The check library: a workflow's done criteria.

A workflow version declares its checks in ``workflow_contract.checks``::

    {"type": "tool_called", "params": {"tools": ["knowledge_search"]}, "blocking": true,
     "description": "At least one search before answering"}

Every check is a closed type, evaluated deterministically over what one turn produced
(:class:`TurnEvidence`): the successful tool calls, the artifacts, the answer and, for
octryx-claude, the verification gate state (only :data:`EXTERNAL_CHECK_TYPES` over MCP tools run
there). A ``judge`` check (rubric) is advisory and
recorded as ``skipped``: no runtime runs a model judge yet, the rubric documents the intent.

Outcomes: ``passed``, ``failed``, ``not_applicable`` (nothing to judge, e.g. citations without
any source) and ``skipped``. A failed ``blocking`` check holds the turn.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

PASSED = "passed"
FAILED = "failed"
NOT_APPLICABLE = "not_applicable"
SKIPPED = "skipped"

CHECK_TYPES = (
    "tool_called",
    "tool_not_called",
    "evidence_count",
    "artifact_created",
    "citations_present",
    # Distinct http(s) URLs in what the phase wrote (its files, else its answer; ``urls``): a research phase's sources.
    "urls_cited",
    "answer_contains_any",
    "field_present",
    "test_command_passed",
    # TDD evidence over per-test results (``test_results``).
    "tests_red",
    "tests_green",
    "confirmed_tests_intact",
    "ci_green",
    "reproduces",
    # The independent reviewer's verdict on the current change (``workflow_runs.review``).
    "review_passed",
    "artefact_review_passed",
    # Every delegated slice merged into the run's working copy (``workflow_runs.slices``).
    "slices_merged",
    # The Work item's Definition of Ready is complete (``workflow_runs.definition_of_ready``).
    "definition_of_ready",
    "specification_ready",
    # The repository's declared lint command passed on the run's change (``workflow_runs/workspace/declared_lint``).
    "lint_passed",
    # The CI failure of the pushed commit is fixed on fresh evidence (``workflow_runs/ci_return``).
    "ci_findings_addressed",
    # Every required evidence family answered for the run's alert target and window (``evidence_families``).
    "evidence_families",
    "judge",
)
ADVISORY_ONLY_TYPES = frozenset({"judge"})
# What octryx-claude's Stop gate can check: the platform tools it called over MCP and the test gate. The
# answer text, artifacts and tool result shapes are not visible there; such checks stay chat-only.
TOOL_CHECK_TYPES = frozenset({"tool_called", "tool_not_called", "evidence_count"})
EXTERNAL_CHECK_TYPES = TOOL_CHECK_TYPES | {"test_command_passed"}
MAX_CHECKS = 20
# The platform's read tools (a device's own reads count as them, ``agent_gateway.read_evidence``). A ``tool_called``
# over these only asks "the code was read": not applicable when the platform knows there is nothing to read
# (``TurnEvidence.workspace_empty``).
READ_TOOLS = frozenset({"read_workspace_file", "grep_workspace", "glob_workspace_files", "list_workspace_directory"})
NOTHING_TO_READ = "the run's working copy holds no file to read (empty repository)"


@dataclass(frozen=True, slots=True)
class ToolUse:
    name: str
    succeeded: bool
    result: Any = None
    params: Any = None
    call_id: str = ""  # Persisted server ToolCall identity, carried only by trusted history writers.


@dataclass(slots=True)
class TurnEvidence:
    tools: list[ToolUse] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    cited_count: int | None = None
    source_count: int | None = None
    verification_state: str | None = None
    # The test runs this evidence covers (newest last), the confirmed tests, CI and the confirmed symptom.
    test_runs: list[dict[str, Any]] = field(default_factory=list)
    confirmed_tests: list[str] = field(default_factory=list)
    # Each confirmed test's role (``workflow_runs/test_roles``: new / regression; empty: every test is new).
    confirmed_test_roles: dict[str, str] = field(default_factory=dict)
    # The newest base run of the confirmed and changed test files (``context.red_on_base``).
    red_on_base: dict[str, Any] | None = None
    red_seen: bool = False
    ci_state: str | None = None
    symptom: str | None = None
    # A confirmed test whose recorded content changed since confirmation (or cannot be verified): its reason.
    confirmed_test_drift: list[str] = field(default_factory=list)
    # The independent reviewer's verdict on the current change (``None``: no review of this change).
    review: dict[str, Any] | None = None
    # The run's slices (``None``: none delegated).
    slices: list[dict[str, Any]] | None = None
    # The Definition of Ready the triage phase recorded (``None``: none).
    definition_of_ready: dict[str, Any] | None = None
    # Server-resolved specification readiness; stored records alone are not source authority.
    specification: dict[str, Any] = field(default_factory=dict)
    # A test command whose runner could not start (``test_command_outcome``): the run's environment, not the agent.
    environment_failure: dict[str, Any] | None = None
    # The declared lint command's run on the run's copy (``declared_lint``; ``None``: none declared or ran).
    lint: dict[str, Any] | None = None
    # A pending CI failure's verdict on this turn's fresh evidence (``ci_return``; ``None``: none pending).
    ci_fix: dict[str, Any] | None = None
    # The phase's evidence family records (``evidence_families.EvidenceRecord`` dicts; empty: classify ``tools``)
    # and the run's alert scope (``evidence_families.alert_gate_scope``; ``None``: no mapped alert target).
    evidence_records: list[dict[str, Any]] = field(default_factory=list)
    alert_scope: dict[str, Any] | None = None
    # The platform established that the run's working copy holds no file (``workflow_runs/workspace/empty_copy``),
    # never the agent's word: a read-only ``tool_called`` check is then ``not_applicable``.
    workspace_empty: bool = False
    # What the phase wrote, per repository path: the added lines of the device's change, or the content of the
    # platform write tools' calls (``urls.written_texts``). ``urls_cited`` reads it.
    written_files: dict[str, str] = field(default_factory=dict)

    def succeeded(self, name: str) -> list[ToolUse]:
        return [use for use in self.tools if use.name == name and use.succeeded]


@dataclass(frozen=True, slots=True)
class CheckResult:
    type: str
    outcome: str
    blocking: bool
    description: str
    detail: str
    # A failed TDD check the platform could not judge (``test_results.evidence_unresolved``): not the agent's
    # failure — the run pauses ``evidence_unresolved`` instead of consuming a loop.
    unresolved: bool = False
    # Fail open on uncertainty: the check could not decide with certainty, so it
    # passed with this note; the caller records it as a ``check_uncertain`` event (``workflow_runs.uncertain``).
    uncertain: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "outcome": self.outcome, "blocking": self.blocking,
                "description": self.description, "detail": self.detail,
                **({"unresolved": True} if self.unresolved else {}),
                **({"uncertain": self.uncertain} if self.uncertain else {})}


# A check function that cannot decide returns ``(PASSED, UNCERTAIN + why)``: it passes, and says why it was unsure.
UNCERTAIN = "uncertain: "


def _names(value: Any) -> list[str]:
    return [str(item).strip() for item in value or [] if str(item or "").strip()] if isinstance(value, list) else []


def _int(value: Any, default: int) -> int:
    return value if type(value) is int and value >= 0 else default


def validate_checks(raw: Any) -> list[dict[str, str]]:
    """Closed validation for a workflow version's ``checks``; ``[]`` when valid or absent."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_CHECKS:
        return [{"code": "invalid_checks", "message": f"checks must be a list of at most {MAX_CHECKS} checks"}]
    errors = []
    for index, item in enumerate(raw):
        check = item if isinstance(item, Mapping) else {}
        kind = str(check.get("type") or "")
        if kind not in CHECK_TYPES:
            message = f"checks[{index}].type must be one of {', '.join(CHECK_TYPES)}"
            errors.append({"code": "unknown_check_type", "message": message})
            continue
        if kind in ADVISORY_ONLY_TYPES and check.get("blocking") is True:
            errors.append({"code": "judge_check_blocking", "message": f"checks[{index}]: a judge check is advisory"})
        if check.get("params") is not None and not isinstance(check.get("params"), Mapping):
            errors.append({"code": "invalid_check_params", "message": f"checks[{index}].params must be an object"})
        if kind == "specification_ready":
            from ..workflow_runs.specification.integration import KINDS

            params = check.get("params")
            if (not isinstance(params, Mapping) or set(params) != {"kind"}
                    or type(params.get("kind")) is not str or params["kind"] not in KINDS):
                errors.append({"code": "invalid_check_params", "message": "specification_ready needs one known kind"})
        if kind == "evidence_families":
            errors.extend(_family_params_errors(index, check.get("params")))
        if kind == "urls_cited":
            from .urls import params_error

            if (message := params_error(check.get("params"))) is not None:
                errors.append({"code": "invalid_check_params", "message": f"checks[{index}]: {message}"})
    return errors


def _family_params_errors(index: int, params: Any) -> list[dict[str, str]]:
    from .evidence_families import FAMILIES

    params = params if isinstance(params, Mapping) else {}
    required = params.get("required", [])
    from_target = params.get("from_target", False)
    fallback = params.get("without_target", {"min_count": 1})
    fallback_ok = (isinstance(fallback, Mapping) and set(fallback) == {"min_count"}
                   and type(fallback["min_count"]) is int and fallback["min_count"] >= 1)
    if (set(params) - {"required", "from_target", "without_target"} or type(from_target) is not bool
            or not isinstance(required, list) or any(item not in FAMILIES for item in required)
            or not (required or from_target) or not fallback_ok):
        message = (f"checks[{index}]: evidence_families needs required (of {', '.join(FAMILIES)}) "
                   "and/or from_target: true")
        return [{"code": "invalid_check_params", "message": message}]
    return []


TDD_CHECK_TYPES = frozenset({"tests_red", "tests_green", "confirmed_tests_intact", "ci_green", "reproduces"})


def _slices(params: Mapping[str, Any], evidence: TurnEvidence) -> tuple[str, str]:
    slices = list(evidence.slices or [])
    minimum = _int(params.get("min_slices"), 0)
    if len(slices) < minimum:
        return FAILED, f"{len(slices)} of at least {minimum} slices delegated"
    open_ = [f"{item.get('key')} {item.get('status')}" for item in slices if item.get("status") != "merged"]
    return (FAILED, "not merged: " + ", ".join(open_[:10])) if open_ else (PASSED, "")


def _review(evidence: TurnEvidence) -> tuple[str, str]:
    from ..workflow_runs.review.verdict import verdict_from_record

    verdict = verdict_from_record(evidence.review)
    if verdict is None:
        return FAILED, "no independent review of the current change"
    if not dict(evidence.review or {}).get("has_change"):
        return FAILED, "the independent review saw no change"
    if verdict.passed:
        return PASSED, ""
    return FAILED, "; ".join(finding.render() for finding in verdict.findings[:10])


def _tdd_unresolved(kind: str, params: Mapping[str, Any], evidence: TurnEvidence) -> str:
    """Why the platform cannot judge this TDD check on the newest test run (empty: it can)."""
    from .test_results import evidence_unresolved

    if kind == "ci_green" or not evidence.test_runs:
        return ""
    confirmed = _names(params.get("tests")) or list(evidence.confirmed_tests)
    suite = kind == "reproduces" and params.get("regression") == "suite"
    return "; ".join(evidence_unresolved(judged_run(evidence.test_runs), confirmed, suite=suite)[:3])


_QUOTED = re.compile(r"'([^']{1,80})'|\"([^\"]{1,80})\"")


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^\w.'\"-]+", " ", text.lower()).split())


def shows_symptom(symptom: str, message: str) -> bool:
    """Whether a failure message shows the submitted symptom: one contains the other (punctuation and spacing
    aside), or every quoted value of the symptom is in the message. A symptom written
    as prose ("... Assertion: expected '15.0', actual '1.0'.") and a Dart message reading "Expected: '15.0' Actual:
    '1.0' ..." never pass a whole-text match."""
    plain_symptom, plain_message = _plain(symptom), _plain(message)
    if plain_symptom and (plain_symptom in plain_message or (plain_message and plain_message in plain_symptom)):
        return True
    quoted = [first or second for first, second in _QUOTED.findall(symptom)]
    return bool(quoted) and all(value.lower() in message.lower() for value in quoted)


def judged_run(runs: list[Any]) -> Any:
    """The run the confirmed-test checks judge: the last one, except a pipeline run that names no test at all (a
    declared system test script). When a pipeline runs `flutter test` (the
    whole suite, passed) and then `python3 system_test/run_system_test.py`, judging the system test run would find
    the confirmed Dart tests "missing from the last test run" and pause the run at the review loop's limit."""
    for run in reversed(runs):
        if not (isinstance(run, Mapping) and run.get("source") == "pipeline" and not run.get("results")
                and not run.get("suite_passed") and not run.get("unresolved")):
            return run
    return runs[-1]


EXISTING_TESTS_RED_ON_BASE = "red_on_base"
_RED_ON_BASE = ("failed", "error")


def _proven_on_base(roles: dict[str, str], confirmed: list[str], params: Mapping[str, Any],
                    evidence: TurnEvidence) -> tuple[dict[str, str], str]:
    """``reproduces`` with ``existing_tests: "red_on_base"`` (an agent may correct
    the existing test that asserted the bug; without this the gate says "only a new test can be red"): a changed
    existing confirmed test counts as the reproduction when the newest base run (``context.red_on_base``) saw it
    fail on the base commit. The proof decides, not the file status. ``(roles, why it is refused)``; the default
    (``new_only``) leaves the roles as they are."""
    if params.get("existing_tests") != EXISTING_TESTS_RED_ON_BASE:
        return roles, ""
    proof = dict(evidence.red_on_base or {})
    outcomes = dict(proof.get("tests") or {})
    unnamed = [str(item) for item in proof.get("unnamed_changes") or []]
    if unnamed:
        return roles, (f"{', '.join(unnamed[:5])} changed, but none of its tests is in the reproduction: name the "
                       "changed test as a confirmed test or undo the change")
    existing = [item for item in confirmed if roles.get(item) == "regression"]
    if not existing:
        return roles, ""
    unproven = [item for item in existing if outcomes.get(item) not in _RED_ON_BASE]
    if unproven:
        seen = "; ".join(f"{item}: {outcomes.get(item) or 'not run'} on base" for item in unproven[:5])
        reason = str(proof.get("reason") or "no base run of the changed tests yet")
        return roles, (f"a changed existing test counts only when it fails on the base commit ({seen}); {reason}")
    return {**roles, **dict.fromkeys(existing, "new")}, ""


def _tdd(kind: str, params: Mapping[str, Any], evidence: TurnEvidence) -> tuple[str, str]:
    from .test_output import FAILED as TEST_FAILED
    from .test_results import all_green, all_red, confirmed_outcomes, intact, suite_regressions

    if kind == "ci_green":
        if evidence.ci_state is None:
            return NOT_APPLICABLE, "no CI result recorded"
        return (PASSED, "") if evidence.ci_state == "succeeded" else (FAILED, f"CI {evidence.ci_state}")
    if not evidence.test_runs:
        return FAILED, "no test run recorded"
    last = judged_run(evidence.test_runs)
    named = _names(params.get("tests"))
    confirmed = named or list(evidence.confirmed_tests)
    roles = {} if named else dict(evidence.confirmed_test_roles or {})
    if kind == "tests_red":
        ok, why = all_red(last, confirmed, roles)
    elif kind == "confirmed_tests_intact":
        ok, why = intact(last, confirmed)
        if ok and evidence.confirmed_test_drift:
            ok, why = False, "; ".join(evidence.confirmed_test_drift[:3])
    elif kind == "tests_green":
        ok, why = all_green(last, confirmed)
        if ok and confirmed and params.get("require_red_first", True) is not False and not evidence.red_seen:
            ok, why = False, "the confirmed tests were never seen failing before they passed"
        if ok and evidence.confirmed_test_drift:
            # Green on a rewritten test proves nothing about the code: the confirmed content must be unchanged.
            ok, why = False, "; ".join(evidence.confirmed_test_drift[:3])
    else:
        roles, refused = _proven_on_base(roles, confirmed, params, evidence)
        ok, why = (False, refused) if refused else all_red(last, confirmed, roles)
        broken = suite_regressions(last, confirmed) if params.get("regression") == "suite" else []
        if ok and broken:
            # C: only the reproduction is red; the rest of the suite is regression and keeps passing.
            ok, why = False, f"regression tests fail: {', '.join(broken[:5])}"
        symptom = str(params.get("symptom") or evidence.symptom or "").strip().lower()
        if ok and symptom:
            messages = [value.get("message", "").lower() for values in confirmed_outcomes(last, confirmed).values()
                        for value in values if value.get("outcome") == TEST_FAILED]
            if not any(message.strip() for message in messages):
                # Fail open: the tests are red, only their message was cut (e.g. by tail);
                # the platform cannot tell the symptom, so it passes and says so instead of looping the agent.
                return PASSED, (UNCERTAIN + "the confirmed tests fail, but the newest run shows no failure message "
                                "(its output was cut), so the symptom could not be compared")
            elif not any(shows_symptom(symptom, message) for message in messages):
                ok, why = False, "the failure does not show the confirmed symptom"
    return (PASSED, "") if ok else (FAILED, why)


def read_only_tool_check(check: Mapping[str, Any]) -> bool:
    """A ``tool_called`` check that asks only for the platform's read tools ("the code was read")."""
    params = check.get("params") if isinstance(check.get("params"), Mapping) else {}
    tools = _names(params.get("tools"))
    return check.get("type") == "tool_called" and bool(tools) and all(name in READ_TOOLS for name in tools)


def _evaluate(kind: str, params: Mapping[str, Any], evidence: TurnEvidence) -> tuple[str, str]:
    tools = _names(params.get("tools"))
    if kind == "tool_called":
        called = [name for name in tools if evidence.succeeded(name)]
        ok = bool(called) if params.get("any") is True else len(called) == len(tools) and bool(tools)
        missing = [name for name in tools if name not in called]
        if not ok and evidence.workspace_empty and read_only_tool_check({"type": kind, "params": params}):
            return NOT_APPLICABLE, NOTHING_TO_READ
        return (PASSED, "") if ok else (FAILED, f"not called: {', '.join(missing)}")
    if kind == "tool_not_called":
        used = [name for name in tools if any(use.name == name for use in evidence.tools)]
        return (FAILED, f"called: {', '.join(used)}") if used else (PASSED, "")
    if kind == "evidence_count":
        minimum = _int(params.get("min_count"), 1)
        count = sum(1 for use in evidence.tools if use.succeeded and (not tools or use.name in tools))
        return (PASSED, "") if count >= minimum else (FAILED, f"{count} of {minimum} evidence calls")
    if kind == "artifact_created":
        wanted = str(params.get("artifact_type") or "").strip()
        minimum = _int(params.get("min_count"), 1)
        count = sum(1 for item in evidence.artifacts if not wanted or str(item.get("type") or "") == wanted)
        return (PASSED, "") if count >= minimum else (FAILED, f"{count} of {minimum} {wanted or 'artifacts'}")
    if kind == "citations_present":
        if not evidence.source_count:
            return NOT_APPLICABLE, "no source in this turn"
        return (PASSED, "") if (evidence.cited_count or 0) > 0 else (FAILED, "the answer cites no source")
    if kind == "urls_cited":
        from .urls import evaluate_urls_cited

        return evaluate_urls_cited(params, evidence.written_files, evidence.answer)
    if kind == "answer_contains_any":
        values = _names(params.get("values"))
        found = any(value.lower() in evidence.answer.lower() for value in values)
        return (PASSED, "") if found else (FAILED, "none of the expected terms in the answer")
    if kind == "field_present":
        tool, name = str(params.get("tool") or ""), str(params.get("field") or "")
        minimum = _int(params.get("min_count"), 1)
        uses = evidence.succeeded(tool)
        value = uses[-1].result.get(name) if uses and isinstance(uses[-1].result, Mapping) else None
        size = len(value) if isinstance(value, list | dict) else (value if type(value) is int else 0)
        return (PASSED, "") if size >= minimum else (FAILED, f"{tool}.{name}: {size} of {minimum}")
    if kind == "artefact_review_passed":
        from ..workflow_runs.review.artefact_gate import evaluate

        return evaluate(evidence.review)
    if kind == "review_passed":
        return _review(evidence)
    if kind == "slices_merged":
        return _slices(params, evidence)
    if kind == "definition_of_ready":
        record = evidence.definition_of_ready
        if not record:
            return FAILED, "no Definition of Ready recorded"
        missing = list(record.get("missing") or [])
        return (PASSED, "") if record.get("complete") and not missing else (FAILED, "; ".join(missing[:10]))
    if kind == "specification_ready":
        wanted = params.get("kind")
        state = evidence.specification.get(wanted, {}) if type(wanted) is str else {}
        return ((PASSED, "") if state.get("state") == "passed" else
                (FAILED, state.get("reason") or "No current authorized specification evidence."))
    if kind in TDD_CHECK_TYPES:
        return _tdd(kind, params, evidence)
    if kind == "lint_passed":
        return _lint(evidence.lint)
    if kind == "ci_findings_addressed":
        if not evidence.ci_fix:
            return NOT_APPLICABLE, "no CI failure of the pushed commit is pending"
        return (PASSED, "") if evidence.ci_fix.get("state") == PASSED else (
            FAILED, str(evidence.ci_fix.get("reason") or "the CI failure is not fixed"))
    if kind == "test_command_passed":
        if evidence.verification_state is None:
            return NOT_APPLICABLE, "no test gate on this runtime"
        return (PASSED, "") if evidence.verification_state in ("passed", "not_applicable") else (
            FAILED, f"test gate: {evidence.verification_state}")
    return SKIPPED, "a judge check is advisory and not run automatically"


def _families(params: Mapping[str, Any], evidence: TurnEvidence) -> tuple[str, str, bool]:
    """``evidence_families``: the required families (named, and the alert target's with ``from_target``)."""
    from .evidence_families import evaluate_families, records_of, required_families_of

    required = _names(params.get("required"))
    records = list(evidence.evidence_records) or records_of(evidence.tools)
    if params.get("from_target") is True:
        if not evidence.alert_scope:
            fallback = params.get("without_target")
            if not isinstance(fallback, Mapping):
                return FAILED, "needs_configuration: no mapped alert target on this run", False
            # A run without a mapped target (the mapping is opt-in per Action): the historic count of answered
            # family calls, so an unmapped alert or a manual start keeps working.
            minimum = _int(fallback.get("min_count"), 1)
            count = sum(1 for record in records if record.get("status") in ("ok", "empty"))
            detail = f"no mapped alert target: {count} of {minimum} answered evidence calls"
            return (PASSED if count >= minimum else FAILED), detail, False
        target_families = required_families_of(evidence.alert_scope)
        if not target_families:
            return FAILED, "needs_configuration: the alert target requires no evidence family", False
        required = [*required, *target_families]
    outcome, detail, unresolved, _statuses = evaluate_families(records, required=required, scope=evidence.alert_scope)
    return outcome, detail, unresolved


def _lint(lint: dict[str, Any] | None) -> tuple[str, str]:
    if not lint:
        return NOT_APPLICABLE, "no declared lint command for the run's copy on this server"
    if lint.get("state") == PASSED:
        return PASSED, str(lint.get("note") or "")
    return FAILED, str(lint.get("reason") or "the declared lint command failed")


def externally_checkable(check: Mapping[str, Any], mcp_tools: frozenset[str]) -> bool:
    """Whether octryx-claude's Stop gate can evaluate ``check``: a closed type over tools it reaches."""
    kind = str(check.get("type") or "")
    if kind not in EXTERNAL_CHECK_TYPES:
        return False
    params = check.get("params") if isinstance(check.get("params"), Mapping) else {}
    return kind not in TOOL_CHECK_TYPES or all(name in mcp_tools for name in _names(params.get("tools")))


def evaluate_check(check: Mapping[str, Any], evidence: TurnEvidence) -> CheckResult:
    kind = str(check.get("type") or "")
    params = check.get("params") if isinstance(check.get("params"), Mapping) else {}
    blocking = check.get("blocking") is True and kind not in ADVISORY_ONLY_TYPES
    if kind == "evidence_families":
        outcome, detail, families_unresolved = _families(params, evidence)
        if families_unresolved:
            detail = f"evidence unresolved: {detail}"
        return CheckResult(kind, outcome, blocking, str(check.get("description") or ""), detail,
                           families_unresolved and outcome == FAILED)
    outcome, detail = _evaluate(kind, params, evidence) if kind in CHECK_TYPES else (SKIPPED, "unknown check type")
    unresolved = _tdd_unresolved(kind, params, evidence) if kind in TDD_CHECK_TYPES and outcome == FAILED else ""
    if unresolved:
        detail = f"evidence unresolved: {unresolved}"
    uncertain = detail.removeprefix(UNCERTAIN) if outcome == PASSED and detail.startswith(UNCERTAIN) else ""
    return CheckResult(kind, outcome, blocking, str(check.get("description") or ""), detail, bool(unresolved),
                       uncertain)


def evaluate_checks(checks: Sequence[Mapping[str, Any]], evidence: TurnEvidence) -> list[CheckResult]:
    return [evaluate_check(check, evidence) for check in checks[:MAX_CHECKS] if isinstance(check, Mapping)]


def failed_blocking(results: Sequence[CheckResult]) -> list[CheckResult]:
    return [result for result in results if result.blocking and result.outcome == FAILED]


def unresolved_blocking(results: Sequence[CheckResult]) -> list[CheckResult]:
    """The failed blocking checks the platform could not judge (the run pauses; no loop, no continuation)."""
    return [result for result in failed_blocking(results) if result.unresolved]


def describe_failed(results: Sequence[CheckResult]) -> str:
    """One line per failed check for a reminder or gate detail: description (or type) and why."""
    return "; ".join(
        f"{result.description or result.type}" + (f" ({result.detail})" if result.detail else "") for result in results
    )


def workflow_checks(contract: Any) -> list[dict[str, Any]]:
    raw = contract.get("checks") if isinstance(contract, Mapping) else None
    return [dict(item) for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


__all__ = [
    "ADVISORY_ONLY_TYPES",
    "UNCERTAIN",
    "CHECK_TYPES",
    "EXTERNAL_CHECK_TYPES",
    "FAILED",
    "NOT_APPLICABLE",
    "NOTHING_TO_READ",
    "PASSED",
    "READ_TOOLS",
    "SKIPPED",
    "CheckResult",
    "ToolUse",
    "TurnEvidence",
    "describe_failed",
    "evaluate_check",
    "externally_checkable",
    "evaluate_checks",
    "failed_blocking",
    "read_only_tool_check",
    "unresolved_blocking",
    "validate_checks",
    "workflow_checks",
]
