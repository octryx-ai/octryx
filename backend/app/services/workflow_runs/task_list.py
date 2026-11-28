"""The work item's task list: small, checkable pieces of work with their proof (a task list made from the spec saves
time and failed runs)."""

from __future__ import annotations

import re
from typing import Any

from ..workflow_checks.library import FAILED, CheckResult

CONTEXT_KEY = "task_list"
CHECK_TYPE = "task_list"
MAX_ITEMS = 100  # a guard against a runaway answer, not a cut: a real list never gets near it
_LINE = re.compile(r"^\s*[-*]?\s*\**T(\d{1,3})[.):]\**\s+(.+?)\s*$", re.MULTILINE)
_PROOF_SPLIT = re.compile(r"\|\s*proofs?:", re.IGNORECASE)
_TEST = re.compile(r"[\w./-]+\.py::[\w:\[\]-]+")
_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.MULTILINE)
_ROLE_TAG = re.compile(r"^\[([\w ,/-]+)\]\s*")
SETS_TASK_LIST_KEY = "sets_task_list"
TASKS_KEY = "tasks"

READINESS_RULE = (
    "Then end your answer with the task list for this work item, under the heading 'Task list:', one line per small, "
    "checkable piece of work: 'T<n>. <what is built> | proof: <test file>::<test function>'. Split every acceptance "
    "criterion and every part of the specification the work item needs into items: each API endpoint or rule, each "
    "data file, each screen element (layout, cards, chips, buttons and their disabled state, empty state, texts in "
    "every language). The proof is the test that will show the item works: a unit test for logic, a system test in "
    "the system test folder for anything a user or client sees. Name tests that do not exist yet; the building phase "
    "writes them."
)
BUILD_RULE = (
    "The contract's task_list is the work: carry out every item and write its proof test under exactly the named file "
    "and function. Before you finish, go through the list item by item and check each against the change; in your "
    "summary name every item with done or why not. Never stop to ask whether to go on or to split the work: the "
    "product owner answered at the start, and a long list is still this phase's work. Build the items in order "
    "until every one is done."
)
REVIEW_RULE = (
    "The task list in the task is the agreed work. Check every item against the change: an item the change does not "
    "carry out, or whose proof test is missing or does not test the item, is a finding of severity \"high\" whose fix "
    "starts with the item, for example \"T3: no dish cards are rendered; ...\"."
)


def parse(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for number, line in _LINE.findall(str(text or "")):
        index = int(number)
        parts = _PROOF_SPLIT.split(line, maxsplit=1)
        if index in seen or (len(parts) < 2 and not items):
            continue  # a "T1." line before the list that names no proof is prose, not a task
        seen.add(index)
        # Every task is kept (also tasks naming two proofs, "A and B", or with a trailing
        # "(screenshot ...)"); a task without a proof keeps "" and the gate names it.
        proofs = list(dict.fromkeys(_TEST.findall(parts[1]))) if len(parts) > 1 else []
        text, roles = _role_tag(parts[0].strip().strip("*").strip())
        items.append({"id": f"T{index}", "text": text, "proof": proofs[0] if proofs else "", "proofs": proofs,
                      **({"roles": roles} if roles else {})})
        if len(items) >= MAX_ITEMS:
            break
    return items


def _role_tag(text: str) -> tuple[str, list[str]]:
    match = _ROLE_TAG.match(text)
    if not match:
        return text, []
    roles = [role.strip().lower() for role in re.split(r"[,/]", match.group(1)) if role.strip()]
    return text[match.end():].strip(), list(dict.fromkeys(roles))


def phase_roles(config: Any) -> list[str]:
    value = dict(config or {}).get(TASKS_KEY)
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [str(role).strip().lower() for role in values if str(role).strip()]


def for_roles(items: list[dict[str, Any]], roles: list[str]) -> list[dict[str, Any]]:
    if not roles:
        return items
    return [item for item in items if not item.get("roles") or set(item["roles"]) & set(roles)]


def sets_task_list(config: Any) -> bool:
    return dict(config or {}).get(SETS_TASK_LIST_KEY) is True


def proofs_of(item: dict[str, Any]) -> list[str]:
    listed = [str(proof) for proof in item.get("proofs") or [] if proof]
    return listed or ([str(item["proof"])] if item.get("proof") else [])


def run_task_list(run: Any, prefer: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    context = dict(run.context or {})
    stored = context.get(CONTEXT_KEY)
    if isinstance(stored, list) and stored:
        return [dict(item) for item in stored if isinstance(item, dict)]
    answers = dict(context.get("answers") or {})
    for key in dict.fromkeys((*prefer, "readiness", *answers.keys())):
        items = parse(str(answers.get(key) or ""))
        if items:
            return items
    return []


def task_list_nodes(graph: Any) -> tuple[str, ...]:
    return tuple(node_id for node_id, node in dict(getattr(graph, "nodes", None) or {}).items()
                 if sets_task_list(getattr(node, "config", None)))


def render(items: list[dict[str, Any]]) -> str:
    def tag(item: dict[str, Any]) -> str:
        return f"[{', '.join(item['roles'])}] " if item.get("roles") else ""

    return "\n".join(f"{item['id']}. {tag(item)}{item['text']} | proof: {', '.join(proofs_of(item)) or '(none named)'}"
                     for item in items)


_HUNK_TEST = re.compile(r"^@@ [^@]* @@\s*(?:async\s+)?def (test_\w+)\(")


def _added_tests(patch: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    current = ""
    hunk_test = ""
    for line in patch.splitlines():
        header = _DIFF_FILE.match(line)
        if header:
            current, hunk_test = header.group(2), ""
            continue
        if line.startswith("@@"):
            match = _HUNK_TEST.match(line)
            hunk_test = match.group(1) if match else ""
            continue
        context = re.match(r"^ (?:async\s+)?def (test_\w+)\(", line)
        if current and context:
            hunk_test = context.group(1)  # an unchanged ``def`` inside the hunk: the lines below belong to it
            continue
        match = re.match(r"^\+\s*(?:async\s+)?def (test_\w+)\(", line)
        if current and match:
            found.setdefault(current, set()).add(match.group(1))
            hunk_test = match.group(1)
        elif current and hunk_test and line.startswith("+") and not line.startswith("+++") and line[1:].strip():
            if re.match(r"^\+(?:async\s+)?def \w+\(|^\+class \w+", line):
                hunk_test = ""  # a new top-level function or class ends the test the hunk started in
                continue
            found.setdefault(current, set()).add(hunk_test)
    return found


def passed_tests(run: Any) -> frozenset[str]:
    seen: dict[str, str] = {}
    for entry in reversed(list(dict(dict(run.context or {}).get("tests") or {}).get("runs") or [])):
        for test_id, result in dict(dict(entry).get("results") or {}).items():
            key = str(test_id).split("[")[0]
            if key not in seen:
                seen[key] = str(dict(result).get("outcome") if isinstance(result, dict) else result)
    return frozenset(key for key, outcome in seen.items() if outcome == "passed")


def missing_proofs(items: list[dict[str, Any]], change: Any,
                   passed: frozenset[str] = frozenset()) -> list[str] | None:
    if not isinstance(change, dict) or change.get("base_unavailable") or change.get("truncated"):
        return None
    patch = change.get("patch")
    if not isinstance(patch, str):
        return None
    added = _added_tests(patch)
    missing: list[str] = []
    for item in items:
        proofs = proofs_of(item)
        absent = []
        for proof in proofs:
            path, _sep, name = proof.partition("::")
            name = name.split("[")[0].split("::")[-1]
            if not path or not name or (name not in added.get(path, set()) and f"{path}::{name}" not in passed):
                absent.append(proof)
        if not proofs:
            missing.append(f"{item['id']} (no proof test named)")
        elif absent:
            missing.append(f"{item['id']} ({', '.join(absent)})")
    return missing


def proof_outcome(proof: str, results: dict[str, Any]) -> str:
    from ..workflow_checks.test_ids import normalize

    path, _sep, rest = normalize(proof).partition("::")
    name = rest.split("[")[0].split("::")[-1]
    outcomes = []
    for test_id, result in results.items():
        outcome = str(dict(result).get("outcome") if isinstance(result, dict) else result)
        base = str(test_id).split("[")[0]
        if base == path and outcome != "passed":
            outcomes.append(outcome)  # the file failed to collect: none of its tests ran
        elif base.partition("::")[0] == path and base.split("::")[-1] == name:
            outcomes.append(outcome)
    if not outcomes:
        return "not run"
    return next((outcome for outcome in outcomes if outcome != "passed"), "passed")


def unproven(items: list[dict[str, Any]], results: dict[str, Any]) -> list[str]:
    missing = []
    for item in items:
        proofs = proofs_of(item)
        if not proofs:
            missing.append(f"{item['id']} (no proof test named)")
            continue
        failed = [f"{proof}: {outcome}" for proof in proofs if (outcome := proof_outcome(proof, results)) != "passed"]
        if failed:
            missing.append(f"{item['id']} ({'; '.join(failed)})")
    return missing


def task_list_result(items: list[dict[str, Any]], change: Any,
                     passed: frozenset[str] = frozenset()) -> CheckResult | None:
    if not items:
        return None
    missing = missing_proofs(items, change, passed)
    if not missing:
        return None
    return CheckResult(type=CHECK_TYPE, outcome=FAILED, blocking=True, detail="",
                       description=("Task list: no proof test in the change for " + ", ".join(missing[:10])
                                    + ": write each named test (file and function exactly as listed) and make it pass"))


__all__ = ["SETS_TASK_LIST_KEY", "TASKS_KEY", "for_roles", "phase_roles", "sets_task_list", "task_list_nodes",
           "passed_tests", "proof_outcome", "unproven", "proofs_of",
           "BUILD_RULE", "CHECK_TYPE", "CONTEXT_KEY", "READINESS_RULE", "REVIEW_RULE", "missing_proofs", "parse",
           "render", "run_task_list", "task_list_result"]
