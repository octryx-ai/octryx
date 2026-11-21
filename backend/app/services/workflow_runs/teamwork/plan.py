"""The coordinator's work plan: its validation and how a revision changes the running split.

The coordinator submits ``{"contract", "items": [{id, title, role, model?, depends_on, paths, appends_to?,
instructions, proofs, reopen?}]}`` with ``submit_work_plan``. A refusal lists every problem at once (a refused
submission is a failed tool call, as for every phase output), so a weak model fixes the plan in one go instead of one
problem per call.

Two items are *concurrent* when neither is an ancestor of the other through ``depends_on``: they may run at the same
time in their own working copies, so the paths they own may not overlap (refuse,
not warn) — otherwise their merges would conflict and the run would loop back for nothing. Dependent items run one
after the other on the merged state and may share paths.

Shared files (otherwise ``pyproject.toml``, the router ``app.js`` and ``i18n.js``
belonged to one
item each, so a later screen could register neither its route nor its texts): each shared file has one owner item,
and an item that depends on the owner (directly or through others) may name it in ``appends_to`` to add its own
entries there. It then writes those files too (its path rules), and for the overlap check they count as its paths, so
two items that append to the same file must depend on each other. The simplest rule that keeps merges clean: the
owner is merged before any appender starts, and appenders of one file run one after the other.

No upper bound on the number of items (no artificial limits). A model the Workspace refuses is not
refused here: it falls back at start with the existing ``run_turn_model_refused`` event.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Any

from . import BLOCKED, CONFLICT, DONE, FAILED, MERGED, PENDING, RUNNING

ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")  # the slice key pattern: it names a git branch and a folder
ITEM_FIELDS = ("id", "title", "role", "model", "depends_on", "paths", "appends_to", "instructions", "proofs")
# What the coordinator decides about an item; a change to any of them is a new piece of work (reopen).
WORK_FIELDS = ("title", "role", "model", "depends_on", "paths", "appends_to", "instructions", "proofs")
WILDCARDS = "*?["
MAX_TEXT = 20_000  # a guard against a runaway argument only; real instructions never get near it


def _text(value: Any, limit: int = 300) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [_text(item, 500) for item in value if _text(item, 500)] if isinstance(value, list) else []


def _item(raw: Any, index: int) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    from ...workflow_checks.test_ids import normalize

    return {
        "id": _text(raw.get("id"), 80).lower() or f"item-{index}",
        "title": _text(raw.get("title"), 300) or _text(raw.get("id"), 80),
        "role": _text(raw.get("role"), 80).lower(),
        "model": _text(raw.get("model"), 200) or None,
        "depends_on": list(dict.fromkeys(_text(item, 80).lower() for item in _strings(raw.get("depends_on")))),
        "paths": folder_globs(_strings(raw.get("paths"))),
        "appends_to": list(dict.fromkeys(_strings(raw.get("appends_to")))),
        "instructions": _text(raw.get("instructions"), MAX_TEXT),
        "proofs": list(dict.fromkeys(normalize(item) for item in _strings(raw.get("proofs")) if normalize(item))),
        "reopen": raw.get("reopen") is True,
    }


def folder_globs(paths: list[str]) -> list[str]:
    """``dir/`` becomes ``dir/**``, and a bare name without a wildcard or a suffix (``src/kitchen-helper/api``) also
    gets ``<name>/**`` next to it, so it names the folder's files (it may still be a file such as ``Makefile``).
    Otherwise ``src/kitchen-helper/api/`` was accepted, but no file inside matched it,
    so every write of the item was refused and it stalled."""
    out: list[str] = []
    for path in paths:
        bare = path.rstrip("/")
        if not bare:
            continue
        if path.endswith("/"):
            out.append(f"{bare}/**")
        elif not any(char in path for char in WILDCARDS) and "." not in path.rsplit("/", 1)[-1]:
            out += [path, f"{path}/**"]
        else:
            out.append(path)
    return list(dict.fromkeys(out))


def ancestors(items: dict[str, dict[str, Any]], key: str) -> set[str]:
    """Every item ``key`` waits for, directly or through others."""
    seen: set[str] = set()
    stack = list(items.get(key, {}).get("depends_on") or [])
    while stack:
        current = stack.pop()
        if current in seen or current not in items:
            continue
        seen.add(current)
        stack.extend(items[current].get("depends_on") or [])
    return seen


def concurrent(items: dict[str, dict[str, Any]], a: str, b: str) -> bool:
    return a != b and a not in ancestors(items, b) and b not in ancestors(items, a)


def overlaps(first: str, second: str) -> bool:
    """Whether two path globs can name the same file (``server/**`` and ``server/search/api.ts`` do).

    ``fnmatch`` of one pattern against the other misses globs that cross folders: ``src/**/*.py`` and
    ``src/kitchen-helper/web/**`` both match ``src/kitchen-helper/web/x.py``. A wildcard
    matches any text,
    ``/`` included (``path_matches``), so two globs can meet when the literal text before their first wildcard is a
    prefix of the other's and the literal text after their last wildcard is a suffix of the other's; the parts in
    between are taken to meet (a refused plan costs one resubmission, a missed overlap a merge conflict and a
    replan)."""
    from ..protected_paths import path_matches

    if not _wild(first) or not _wild(second):
        literal, pattern = (first, second) if not _wild(first) else (second, first)
        return literal == pattern or path_matches(literal, pattern)
    if fnmatchcase(first, second) or fnmatchcase(second, first):
        return True
    heads = _head(first), _head(second)
    tails = _tail(first), _tail(second)
    return (heads[0].startswith(heads[1]) or heads[1].startswith(heads[0])) and (
        tails[0].endswith(tails[1]) or tails[1].endswith(tails[0]))


def _wild(pattern: str) -> bool:
    return any(char in pattern for char in WILDCARDS)


def _head(pattern: str) -> str:
    """The literal text before the first wildcard (``**/`` at the start may also match nothing: no head)."""
    return re.split(r"[*?\[]", pattern, maxsplit=1)[0]


def _tail(pattern: str) -> str:
    """The literal text after the last wildcard (a ``[...]`` class counts as a wildcard)."""
    return re.split(r"[*?\]]", pattern)[-1]


def _cycle(items: dict[str, dict[str, Any]]) -> list[str]:
    """The items on a dependency cycle (Kahn's order leaves them over), ``[]`` without one."""
    incoming = {key: sum(1 for dep in item["depends_on"] if dep in items and dep != key)
                for key, item in items.items()}
    ready = [key for key, count in incoming.items() if count == 0]
    while ready:
        current = ready.pop()
        for key, item in items.items():
            if current in item["depends_on"] and current != key:
                incoming[key] -= 1
                if incoming[key] == 0:
                    ready.append(key)
    return sorted(key for key, count in incoming.items() if count > 0)


def _path_problems(item: dict[str, Any]) -> list[str]:
    if not item["paths"]:
        return [f"{item['id']}: paths lists the files it owns as relative globs (e.g. server/search/**)"]
    bad = [path for path in item["paths"]
           if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path) or ".." in re.split(r"[\\/]", path)]
    return [f"{item['id']}: path {path!r} must be relative to the repository, without '..'" for path in bad]


def validate_plan(raw: Any, *, roles: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    """``(record, problems)``. ``roles``: the ``parallel_work`` node's role templates (``None`` when the plan is
    checked without its node; the role is then only required to be named)."""
    from ...workflow_checks.test_ids import is_canonical

    raw = raw if isinstance(raw, dict) else {}
    listed = raw.get("items") if isinstance(raw.get("items"), list) else []
    items = [_item(entry, index) for index, entry in enumerate(listed, start=1)]
    problems: list[str] = []
    if not items:
        problems.append("items: at least one item")
    ids = [item["id"] for item in items]
    for key in sorted({key for key in ids if ids.count(key) > 1}):
        problems.append(f"{key}: every item needs its own id")
    by_id = {item["id"]: item for item in items}
    for item in items:
        key = item["id"]
        if not ITEM_ID.match(key):
            problems.append(f"{key}: the id is lower case letters, digits and '-' (at most 40, it names a branch)")
        if not item["role"]:
            problems.append(f"{key}: role names who builds it")
        elif roles is not None and item["role"] not in roles:
            problems.append(f"{key}: role {item['role']!r} is not one of {', '.join(sorted(roles)) or 'none'}")
        if key in item["depends_on"]:
            problems.append(f"{key}: an item cannot depend on itself")
        for dep in item["depends_on"]:
            if dep != key and dep not in by_id:
                problems.append(f"{key}: depends on {dep!r}, which is not an item of the plan")
        problems += _path_problems(item)
        problems += _proof_path_problems(item)
        if not item["instructions"]:
            problems.append(f"{key}: instructions say what to build")
        for proof in item["proofs"]:
            if not is_canonical(proof):
                problems.append(f"{key}: proof {proof!r} is not a test id (path/to/test_file.py::test_name)")
        if not item["proofs"] and _needs_proof(roles, item["role"]):
            problems.append(f"{key}: proofs names at least one test that shows the item works")
    cycle = _cycle(by_id)
    if cycle:
        problems.append(f"depends_on goes round in a circle through {', '.join(cycle)}")
    else:
        problems += _append_problems(by_id)
        problems += _overlap_problems(by_id)
        problems += _waiting_test_problems(by_id, roles)
    record = {"contract": _text(raw.get("contract"), MAX_TEXT),
              "items": [{field: item[field] for field in (*ITEM_FIELDS, "reopen")} for item in items]}
    return record, problems


def _proof_path_problems(item: dict[str, Any]) -> list[str]:
    """Each proof's test file lies under the item's own paths: the item writes its proof tests, and the path rule
    refuses any other file. Otherwise frontend items got ``tests/system/...``
    proofs
    while ``tests/system/**`` belonged to the test item; nobody wrote them, the pipeline reported missing proofs and
    the run replanned until its loop limit."""
    from ..protected_paths import path_matches

    problems = []
    for proof in item["proofs"]:
        test_file = proof.split("::", 1)[0]
        if test_file and not any(path_matches(test_file, path) for path in item["paths"]):
            problems.append(f"{item['id']}: proof {proof!r} is outside its paths, so it cannot write that test: give "
                            "this proof to the item that writes the test (or add the test file to this item's paths)")
    return problems


def _append_problems(items: dict[str, dict[str, Any]]) -> list[str]:
    """``appends_to`` names files of an item this one depends on (directly or through others)."""
    from ..protected_paths import path_matches

    problems = []
    for key, item in items.items():
        owners = ancestors(items, key)
        for name in item["appends_to"]:
            if not any(path_matches(name, path) or name == path for owner in owners for path in items[owner]["paths"]):
                problems.append(f"{key}: appends_to {name!r} is no file of an item it depends on: name the item that "
                                "owns it in depends_on, or own the file yourself")
    return problems


STARTS_AT_ONCE = "starts_at_once"  # role template flag: its items build from the contract, never after other items


def starts_at_once(roles: dict[str, Any] | None, role: str) -> bool:
    template = (roles or {}).get(role)
    return isinstance(template, dict) and template.get(STARTS_AT_ONCE) is True


def _waiting_test_problems(items: dict[str, dict[str, Any]], roles: dict[str, Any] | None) -> list[str]:
    """An item of a role that starts at once (the test role) depends only on the owners of the shared files it
    appends to: it writes its tests from the contract (routes, test ids, texts) while the others build, and the
    pipeline runs them on the merged story.

    Otherwise a test item that depended on all four other items started only
    after the last one merged and ran 6.5 minutes alone."""
    from ..protected_paths import path_matches

    problems = []
    for key, item in items.items():
        if not starts_at_once(roles, item["role"]):
            continue
        owners = {owner for name in item["appends_to"] for owner, other in items.items() if owner != key
                  and any(path_matches(name, path) or name == path for path in other["paths"])}
        waits = [dep for dep in item["depends_on"] if dep in items and dep not in owners]
        if waits:
            problems.append(f"{key}: a {item['role']} item writes its tests from the contract while the other items "
                            f"build, so it does not wait for {', '.join(waits)}: drop them from depends_on (the "
                            "pipeline runs its tests on the merged story; only the owner of a shared file it "
                            "appends to may stay)")
    return problems


def _needs_proof(roles: dict[str, Any] | None, role: str) -> bool:
    template = (roles or {}).get(role)
    return not (isinstance(template, dict) and template.get("needs_proof") is False)


def _overlap_problems(items: dict[str, dict[str, Any]]) -> list[str]:
    problems = []
    keys = sorted(items)
    for index, first in enumerate(keys):
        for second in keys[index + 1:]:
            if not concurrent(items, first, second):
                continue
            shared = [f"{a} / {b}" for a in _writes(items[first]) for b in _writes(items[second]) if overlaps(a, b)]
            if shared:
                problems.append(f"{first} and {second} can run at the same time but both own {shared[0]}: give "
                                "each its own paths, or let one depend on the other")
    return problems


def _writes(item: dict[str, Any]) -> list[str]:
    """Every path the item may write: its own and the shared files it appends to."""
    return [*(item.get("paths") or []), *(item.get("appends_to") or [])]


def write_paths(item: dict[str, Any]) -> list[str]:
    """The item's path rules: what it owns plus the shared files it appends to (``appends_to``)."""
    return list(dict.fromkeys(_writes(item)))


def changes_nothing(current: dict[str, dict[str, Any]], record: dict[str, Any]) -> bool:
    """A resubmitted plan that reopens, adds and drops nothing, and retries no stuck item: the split after it is the
    split before it (a merged item whose wording alone changed stays merged, :func:`reopens`)."""
    planned = {item["id"]: item for item in record.get("items") or []}
    if set(planned) != set(current):
        return False
    return not any(current[key].get("status") != MERGED or reopens(current[key], item)
                   for key, item in planned.items())


# --- revision: a new plan against the split that is already running ---------------------------------------------


def _changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Whether a work field differs; a missing field and an empty one are equal."""
    return any((old.get(field) or None) != (new.get(field) or None) for field in WORK_FIELDS)


def _gained(old: dict[str, Any], new: dict[str, Any], field: str) -> bool:
    return bool(set(new.get(field) or []) - set(old.get(field) or []))


def reopens(old: dict[str, Any], planned: dict[str, Any]) -> bool:
    """Whether a re-plan sends a ``merged`` item back to work: only ``reopen: true``, or new work in its plan entry
    (a proof, a path or a shared file it did not have). A merged item whose instructions, title, model or
    dependencies were reworded stays merged and is never built again.

    Otherwise, after a red pipeline, a coordinator that reopened one item and
    wrote
    "Merged and fine; keep unchanged" into the other four items' instructions; each changed text reopened its item,
    so the second round re-ran all five items (6:50 of the story's 28 minutes) for one CSS split; merged items
    were re-run the same way whenever their text changed."""
    return planned.get("reopen") is True or any(_gained(old, planned, field)
                                                for field in ("proofs", "paths", "appends_to"))


def reopen_fields(old: dict[str, Any], reason: str) -> dict[str, Any]:
    """The run state of an item's next iteration: pending again, its own session kept (it resumes), the last result
    and its merge forgotten."""
    return {"status": PENDING, "iteration": int(old.get("iteration") or 1) + 1, "attempts": 0, "result": None,
            "conflicts": None, "finished_at": None, "start_refusals": 0, "start_detail": None, "retry_at": None,
            "reason": reason, "fix": None, "fix_source": None}


def revision_problems(current: dict[str, dict[str, Any]], record: dict[str, Any]) -> list[str]:
    """What a revised plan may not do to the running split: change or drop a running item, or one whose merge is
    still pending (``done``)."""
    new = {item["id"]: item for item in record.get("items") or []}
    problems = []
    for key, old in sorted(current.items()):
        if old.get("status") not in (RUNNING, DONE):
            continue
        if key not in new:
            problems.append(f"{key}: is running and cannot be removed; wait until it ends")
        elif _changed(old, new[key]) or new[key].get("reopen"):
            problems.append(f"{key}: is running and cannot be changed; wait until it ends")
    return problems


def revise(current: dict[str, dict[str, Any]], record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The split after a (re)submitted plan, by the revision rules of design section 2:

    - a ``merged`` item stays merged unless :func:`reopens` (``reopen: true``, or a new proof, path or shared file);
      its reworded fields are kept, so the task list and the team view show the coordinator's latest words;
    - a reopened merged item becomes ``pending`` with ``iteration + 1``; it resumes its own session;
    - a ``running`` / ``done`` item is kept as it is (``revision_problems`` refused changing it);
    - a ``failed``, ``blocked`` or ``conflict`` item the coordinator keeps is tried again (``pending``, next
      iteration): the coordinator saw why it stopped, and keeping it unchanged would only replan again;
    - new items start ``pending``; items left out of the plan are dropped (only ones that are not running).
    """
    split: dict[str, dict[str, Any]] = {}
    for planned in record.get("items") or []:
        key = planned["id"]
        fields = {field: planned.get(field) for field in ITEM_FIELDS}
        old = current.get(key)
        if old is None:
            split[key] = {**fields, **_fresh()}
            continue
        status = old.get("status")
        if status in (RUNNING, DONE):
            split[key] = dict(old)
        elif status == MERGED and not reopens(old, planned):
            split[key] = {**old, **fields}
        elif status == PENDING:
            split[key] = {**old, **fields}
        else:  # merged and reopened, or stuck: its next iteration
            split[key] = {**old, **fields, **reopen_fields(
                old, "reopened" if status == MERGED else f"retry after {status}")}
    return split


def _fresh() -> dict[str, Any]:
    return {"status": PENDING, "iteration": 1, "attempts": 0, "session_id": None, "branch": None, "path": None,
            "base": None, "runtime_target_id": None, "agent_hash": None, "job_id": None, "result": None,
            "reason": None, "conflicts": None, "merged_sha": None, "started_at": None, "finished_at": None,
            "merged_at": None}


STUCK_STATUSES = (FAILED, BLOCKED, CONFLICT)

__all__ = ["ITEM_FIELDS", "ITEM_ID", "STUCK_STATUSES", "ancestors", "changes_nothing", "concurrent", "folder_globs",
           "overlaps", "reopen_fields", "reopens", "revise", "revision_problems", "starts_at_once", "validate_plan",
           "write_paths"]
