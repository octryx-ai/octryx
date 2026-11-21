"""Sample run bundles: export one finished run to a JSON file, import it into the demo as a sample run.

A bundle is real data of one real run: the run with its child and review runs, their events and decisions, the
sessions with messages, tool calls, turn traces and usage, the seat's device job, and the pull request on the
(fake) GitHub with its commits, comments, reviews and statuses. Nothing is invented; the import writes the same
rows through the same models, with new ids, every reference remapped and every time moved so the run ends now.

    python scripts/run_bundle.py export --run RUN_ID --github http://127.0.0.1:8434 [--app-base URL] --out FILE
    python scripts/run_bundle.py check FILE            # the scrub, secret and size checks of an export
    python scripts/run_bundle.py import FILE --workspace "Demo Shop" --github http://127.0.0.1:8434

Export (on the stack that ran it) leaves out what a demo must not carry:
- the people: every human's name, login and e-mail becomes ``demo``, home folders become ``/home/demo``;
- the machine: its device name becomes ``Sample device``, its device id a placeholder for the import's revoked sample
  device, a working folder ``/home/demo/<its last part>``; a
  session's gateway key, grant, launcher folder and every encrypted value (``*_enc``) are left out;
- the prompts: a turn trace keeps its answer, tools and usage, not the model's input or context snapshot;
- the stack: its fake GitHub and app URLs become placeholders the import fills in.
It refuses a bundle with a secret (``secret_patterns.py``), a recording device's id, a stack's private binding or
more than 2 MB (the scrub reads no bigger file).

Import runs only in the demo (``OCTRYX_DEMO=1`` and a non-production runtime profile, fail closed): the demo is its own
install with its own database, so the sample counts there like any run (costs, dashboards), which is what a demo
should show. Every imported run carries the bundle's id in its context (``sample_bundle``), the run views show a
"Sample run" badge for it and the main run's title starts with "Sample run: ". A bundle already imported into the
Workspace is skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

FORMAT = "octryx-run-bundle"
VERSION = 1
MAX_BYTES = 2_000_000
TITLE_PREFIX = "Sample run: "
GIT_BASE = "{{GIT_BASE}}"
APP_BASE = "{{APP_BASE}}"
DEMO_NAME = "demo"
DEMO_EMAIL = "demo@localhost.invalid"
DEMO_HOME = "/home/demo"
DEVICE_NAME = "Sample device"
# Every device of the recording stack (a job's, a run target's, a review seat's): one placeholder the import fills in
# with its revoked "Sample device", keeping recording-machine identifiers out of the imported UI.
DEVICE_PLACEHOLDER = "{{SAMPLE_DEVICE}}"
_DEVICE_ID = re.compile(r"(?<![0-9a-z_])dev_[0-9a-f]{16}(?![0-9a-f])")
# Accounts every install has: their names are no person's and stay.
GENERIC_NAMES = frozenset({"admin", "demo", "system", "root", "user", "bot"})
PR_REVIEW_WORKFLOW = "pr-review-bot"
BACKEND = Path(__file__).resolve().parents[1]

# The tables of a bundle, in insert order (a table's references to earlier ones and to itself are remapped).
TABLES = (
    "sessions", "workflow_runs", "workflow_run_sessions", "workflow_run_events", "workflow_run_decisions",
    "workflow_handoffs", "messages", "tool_calls", "turn_traces", "turn_trace_summaries", "usage_events",
    "device_jobs", "device_job_events",
)
# Columns a demo must not carry: the model's whole input and context per turn (the prompts).
DROPPED = {"turn_traces": {"input_messages_json": [], "context_snapshot_json": {}}}
_HOME = re.compile(r"(?:/Users|/home)/[^/\s\"'\\]+")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


# ---- refusal: only in the demo ---------------------------------------------------------------------------------------

def require_demo() -> None:
    """Import only where the demo is switched on and the runtime is no production one (same switch as the seed)."""
    if os.environ.get("OCTRYX_DEMO") != "1":
        raise SystemExit("run_bundle: refusing to import a sample run outside the demo (OCTRYX_DEMO is not 1)")
    from app.config import get_settings
    from app.four_eyes_dev_policy import DEV_SELF_APPROVAL_PROFILES

    profile = str(get_settings().runtime_profile or "").strip().lower()
    if profile not in DEV_SELF_APPROVAL_PROFILES:
        raise SystemExit(f"run_bundle: refusing to import a sample run in the runtime profile '{profile}'")


# ---- values ----------------------------------------------------------------------------------------------------------

def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$dec": str(value)}
    if isinstance(value, bytes):
        return {"$b64": base64.b64encode(value).decode()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        if "$dt" in value:
            parsed = datetime.fromisoformat(value["$dt"])
            return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
        if "$dec" in value:
            return Decimal(value["$dec"])
        if "$b64" in value:
            return base64.b64decode(value["$b64"])
    return value


def _walk(value: Any, change) -> Any:
    """``value`` with ``change`` applied to every string in it (keys of a mapping included)."""
    if isinstance(value, str):
        return change(value)
    if isinstance(value, list):
        return [_walk(item, change) for item in value]
    if isinstance(value, dict):
        if len(value) == 1 and next(iter(value)) in ("$dt", "$dec", "$b64"):
            return value
        return {_walk(key, change): _walk(item, change) for key, item in value.items()}
    return value


def replacer(pairs: dict[str, str], *, words: bool = False):
    """One pass over a string replacing every key of ``pairs`` (longest first), or the identity when empty;
    ``words``: only where a key stands as a whole word (a name, not a part of another word)."""
    pairs = {old: new for old, new in pairs.items() if old and old != new}
    if not pairs:
        return lambda text: text
    alternatives = "|".join(re.escape(old) for old in sorted(pairs, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w.@-])(?:{alternatives})(?![\w@-]|\.\w)" if words else alternatives,
                         re.IGNORECASE if words else 0)
    lowered = {old.lower(): new for old, new in pairs.items()}
    return lambda text: pattern.sub(lambda match: pairs.get(match[0], lowered.get(match[0].lower(), match[0])), text)


def _models() -> dict[str, Any]:
    import app.models  # noqa: F401 - every mapper registered
    from app.db import Base

    return {mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers
            if getattr(mapper, "local_table", None) is not None}


def _columns(model: Any) -> dict[str, str]:
    """``column name -> attribute key`` of ``model``'s own columns."""
    from sqlalchemy import inspect

    return {prop.columns[0].name: prop.key for prop in inspect(model).column_attrs if len(prop.columns) == 1}


def _row(model: Any, item: Any) -> dict[str, Any]:
    return {name: _encode(getattr(item, key)) for name, key in _columns(model).items()}


# ---- export ----------------------------------------------------------------------------------------------------------

async def collect(db: Any, run_id: str) -> dict[str, Any]:
    """The rows of the run ``run_id``: itself, its child runs, the review runs on its branch and what hangs off them."""
    from sqlalchemy import or_, select

    from app.models import DeviceJobEvent, Session, TurnTraceSummary, WorkflowHandoff
    from app.models import WorkflowRun as Run

    models = _models()
    rows: dict[str, list[Any]] = {name: [] for name in TABLES}
    main = await db.get(Run, run_id)
    if main is None:
        raise SystemExit(f"run_bundle: no run {run_id}")
    if main.status not in ("completed", "stopped", "failed"):
        raise SystemExit(f"run_bundle: the run is {main.status}; export a finished run")
    runs = {main.id: main}
    frontier = [main.id]
    while frontier:
        children = (await db.execute(select(Run).where(Run.parent_run_id.in_(frontier)))).scalars().all()
        frontier = [child.id for child in children if child.id not in runs]
        runs.update({child.id: child for child in children})
    if main.branch and main.repository:
        reviews = (await db.execute(select(Run).where(
            Run.workflow_key == PR_REVIEW_WORKFLOW, Run.project_id == main.project_id,
            Run.repository == main.repository, Run.branch == main.branch,
            Run.created_at >= main.created_at))).scalars().all()
        runs.update({review.id: review for review in reviews})
    ids = list(runs)
    rows["workflow_runs"] = sorted(runs.values(), key=lambda run: run.created_at)
    for table in ("workflow_run_sessions", "workflow_run_events", "workflow_run_decisions"):
        model = models[table]
        rows[table] = list((await db.execute(select(model).where(model.run_id.in_(ids)))).scalars())
    rows["workflow_handoffs"] = [item for item in (await db.execute(select(WorkflowHandoff).where(or_(
        WorkflowHandoff.parent_run_id.in_(ids), WorkflowHandoff.child_run_id.in_(ids))))).scalars()
        if item.parent_run_id in runs and (item.child_run_id is None or item.child_run_id in runs)]
    session_ids = {link.session_id for link in rows["workflow_run_sessions"]}
    frontier = list(session_ids)
    while frontier:
        found = (await db.execute(select(Session.id).where(Session.parent_session_id.in_(frontier)))).scalars()
        frontier = [sid for sid in found if sid not in session_ids]
        session_ids.update(frontier)
    sessions = list((await db.execute(select(Session).where(Session.id.in_(session_ids)))).scalars())
    rows["sessions"] = sorted(sessions, key=lambda item: item.started_at or datetime.min)
    sids = list(session_ids)
    for table in ("messages", "tool_calls", "turn_traces", "usage_events", "device_jobs"):
        model = models[table]
        rows[table] = list((await db.execute(select(model).where(model.session_id.in_(sids)))).scalars())
    trace_ids = [trace.id for trace in rows["turn_traces"]]
    rows["turn_trace_summaries"] = list((await db.execute(select(TurnTraceSummary).where(
        TurnTraceSummary.trace_id.in_(trace_ids)))).scalars()) if trace_ids else []
    job_ids = [job.id for job in rows["device_jobs"]]
    if job_ids:
        rows["device_job_events"] = list((await db.execute(
            select(DeviceJobEvent).where(DeviceJobEvent.job_id.in_(job_ids))
            .order_by(DeviceJobEvent.job_id, DeviceJobEvent.seq))).scalars())
    refs = await _references(db, models, rows)
    tables = {table: [_row(models[table], item) for item in items] for table, items in rows.items()}
    for table, emptied in DROPPED.items():
        for row in tables.get(table, []):
            row.update(emptied)
    return {"main_run": main.id, "tables": tables, "references": refs}


async def _references(db: Any, models: dict[str, Any], rows: dict[str, list[Any]]) -> dict[str, Any]:
    """What the import resolves by name rather than id: the users (bots keep their account), the flow versions, the
    Workspace and the work items."""
    from sqlalchemy import select

    from app.models import FlowDefinition, FlowDefinitionVersion, Project, User, WorkItem
    user_ids, version_ids, item_ids, project_ids = set(), set(), set(), set()
    for table, items in rows.items():
        for name, column in models[table].__table__.columns.items():
            for fk in column.foreign_keys:
                target = fk.column.table.name
                values = {getattr(item, _columns(models[table])[name]) for item in items} - {None}
                {"users": user_ids, "flow_definition_versions": version_ids, "work_items": item_ids,
                 "projects": project_ids}.get(target, set()).update(values)
    users = {user.id: {"username": user.username, "email": user.email, "display_name": user.display_name,
                       "account_type": getattr(user, "account_type", "human") or "human"}
             for user in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()}
    versions = {}
    for version in (await db.execute(select(FlowDefinitionVersion).where(
            FlowDefinitionVersion.id.in_(version_ids)))).scalars():
        flow = await db.get(FlowDefinition, version.flow_id)
        versions[version.id] = {"key": getattr(flow, "key", None), "version": version.version}
    items = {}
    if item_ids:
        for item in (await db.execute(select(WorkItem).where(WorkItem.id.in_(item_ids)))).scalars():
            items[item.id] = {"key": getattr(item, "source_key", None), "title": item.title}
    projects = {}
    if project_ids:
        projects = {project.id: {"name": project.name}
                    for project in (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars()}
    return {"users": users, "flow_definition_versions": versions, "work_items": items, "projects": projects}


_FOLDER_KEYS = ("folder", "root")
# A session's gateway and hook bindings on the recording stack: a key (even encrypted with that stack's secret), a
# grant and the launcher's own folder mean nothing in the demo and never leave the stack.
_PRIVATE_KEYS = frozenset({"gateway_session_key", "oauth_grant_id", "launcher_state_root"})


_PRIVATE_FIELD = re.compile(r'"(' + "|".join(sorted(_PRIVATE_KEYS)) + r'|\w+_enc)"\s*:')


def _drop_private(value: Any) -> Any:
    """``value`` without the stack's private bindings: the keys above and every ``*_enc`` (an encrypted secret)."""
    if isinstance(value, list):
        return [_drop_private(item) for item in value]
    if isinstance(value, dict):
        if len(value) == 1 and next(iter(value)) in ("$dt", "$dec", "$b64"):
            return value
        return {key: _drop_private(item) for key, item in value.items()
                if not (isinstance(key, str) and (key in _PRIVATE_KEYS or key.endswith("_enc")))}
    return value


def _machine(bundle: Any) -> dict[str, str]:
    """The recording machine out of the bundle: its device's name becomes ``Sample device`` and each working folder
    ``/home/demo/<its last part>`` (a folder's parents name the machine's own layout)."""
    found: dict[str, str] = {}

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                text = item.strip() if isinstance(item, str) else ""
                if key == "device_name" and len(text) >= 3:
                    found[text] = DEVICE_NAME
                elif key in _FOLDER_KEYS and text.startswith("/") and text.rstrip("/").count("/") >= 2:
                    found[text.rstrip("/")] = f"{DEMO_HOME}/{PurePosixPath(text.rstrip('/')).name}"
                else:
                    visit(item)

    visit(bundle)
    return found


def sanitize(bundle: dict[str, Any], *, github: str = "", app_base: str = "") -> dict[str, Any]:
    """The people, home folders and the stack's URLs out of every string of ``bundle``."""
    urls: dict[str, str] = {}
    if github:
        urls[github.rstrip("/")] = GIT_BASE
    if app_base:
        urls[app_base.rstrip("/")] = APP_BASE
    names: dict[str, str] = {}
    for user in bundle["references"]["users"].values():
        if user.get("account_type", "human") != "human":
            continue
        for key, demo in (("email", DEMO_EMAIL), ("username", DEMO_NAME), ("display_name", DEMO_NAME)):
            value = str(user.get(key) or "").strip()
            if len(value) >= 3 and value.lower() not in GENERIC_NAMES:
                names[value] = demo
                names.update({part: demo for part in value.split() if len(part) >= 3 and key == "display_name"
                              and part.lower() not in GENERIC_NAMES})
        user.update(username=DEMO_NAME, email=DEMO_EMAIL, display_name=DEMO_NAME)
    for project in bundle["references"]["projects"].values():
        project["name"] = ""  # the import's Workspace takes its place
    bundle = _drop_private(bundle)
    machine = _machine(bundle)
    url, name = replacer({**machine, **urls}), replacer(names, words=True)

    def clean(text: str) -> str:
        return _DEVICE_ID.sub(DEVICE_PLACEHOLDER, _HOME.sub(DEMO_HOME, name(url(text))))

    return _walk(bundle, clean)


# ---- the pull request on the (fake) GitHub ---------------------------------------------------------------------------

def _http(method: str, url: str, body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - the demo's own fake GitHub
        raw = response.read()
    return json.loads(raw) if raw else None


def _git(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})})
    if done.returncode != 0:
        raise SystemExit(f"run_bundle: git {args[0]} failed: {done.stderr.strip()[:300]}")
    return done.stdout


def _demo_identity() -> dict[str, str]:
    return {"GIT_AUTHOR_NAME": DEMO_NAME, "GIT_AUTHOR_EMAIL": DEMO_EMAIL,
            "GIT_COMMITTER_NAME": DEMO_NAME, "GIT_COMMITTER_EMAIL": DEMO_EMAIL}


def export_pull(github: str, repository: str, branch: str) -> dict[str, Any] | None:
    """The pull request of ``branch`` on the fake GitHub: its commits as patches and what was left on it."""
    github = github.rstrip("/")
    pull = next((item for item in _http("GET", f"{github}/_fake/pulls")
                 if item.get("repository") == repository and item["head"]["ref"] == branch), None)
    if pull is None:
        return None
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder) / "repo"
        _git("clone", "-q", f"{github}/{repository}.git", str(work))
        base = _git("merge-base", f"origin/{pull['base']['ref']}", f"origin/{branch}", cwd=work).strip()
        commits = _git("rev-list", "--reverse", f"{base}..origin/{branch}", cwd=work).split()
        patches = [_git("format-patch", "--stdout", "-1", sha, cwd=work) for sha in commits]
    patches = [re.sub(r"(?m)^From: .*$", f"From: {DEMO_NAME} <{DEMO_EMAIL}>", patch) for patch in patches]
    keep = ("number", "title", "body", "state")
    return {"repository": repository, "branch": branch, "base": pull["base"]["ref"], "commits": commits,
            "patches": patches, "pull": {key: pull.get(key) for key in keep}, "head_sha": pull["head"]["sha"],
            "comments": [{key: row.get(key) for key in ("id", "body")} for row in pull.get("comments", [])],
            "reviews": [{key: row.get(key) for key in ("id", "body", "commit_id")} for row in pull.get("reviews", [])],
            "review_comments": [{key: row.get(key) for key in ("id", "review", "path", "line", "body", "commit_id",
                                                                "in_reply_to_id")}
                                for row in pull.get("review_comments", [])],
            "statuses": [{key: row.get(key) for key in ("sha", "state", "context", "description", "target_url")}
                         for row in pull.get("statuses", [])]}


def replay_pull(github: str, recorded: dict[str, Any]) -> dict[str, str]:
    """Push the recorded commits as the branch and open the pull request with its comments, reviews and statuses
    again; ``old -> new`` for the commit shas and the pull request's links. A branch already there is left alone."""
    github = github.rstrip("/")
    repository, branch = recorded["repository"], recorded["branch"]
    api = f"{github}/api/v3/repos/{repository}"
    existing = next((item for item in _http("GET", f"{github}/_fake/pulls")
                     if item.get("repository") == repository and item["head"]["ref"] == branch), None)
    if existing is not None:
        return _pull_pairs(recorded, existing["number"], {})
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder) / "repo"
        _git("clone", "-q", f"{github}/{repository}.git", str(work))
        _git("checkout", "-q", "-b", branch, f"origin/{recorded['base']}", cwd=work)
        for index, patch in enumerate(recorded["patches"]):
            path = Path(folder) / f"{index:04d}.patch"
            path.write_text(patch, encoding="utf-8")
            _git("am", "-q", "--committer-date-is-author-date", str(path), cwd=work, env=_demo_identity())
        base = _git("rev-parse", f"origin/{recorded['base']}", cwd=work).strip()
        commits = _git("rev-list", "--reverse", f"{base}..HEAD", cwd=work).split()
        _git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", cwd=work)
    shas = dict(zip(recorded["commits"], commits, strict=False))
    shas.setdefault(recorded["head_sha"], commits[-1] if commits else "")
    sha = replacer({**shas, **{old[:7]: new[:7] for old, new in shas.items() if old and new}})
    pull = recorded["pull"]
    number = _http("POST", f"{api}/pulls", {"title": pull["title"], "body": sha(pull.get("body") or ""),
                                           "head": branch, "base": recorded["base"]})["number"]
    for comment in recorded["comments"]:
        _http("POST", f"{api}/issues/{number}/comments", {"body": sha(comment.get("body") or "")})
    review_ids: dict[Any, Any] = {}
    comment_ids: dict[Any, Any] = {}
    for review in recorded["reviews"]:
        inline = [row for row in recorded["review_comments"]
                  if row.get("review") == review.get("id") and not row.get("in_reply_to_id")]
        made = _http("POST", f"{api}/pulls/{number}/reviews", {
            "body": sha(review.get("body") or ""), "commit_id": sha(review.get("commit_id") or ""),
            "comments": [{"path": row["path"], "line": row["line"], "body": sha(row.get("body") or "")}
                         for row in inline]})
        review_ids[review.get("id")] = made["id"]
        listed = _http("GET", f"{api}/pulls/{number}/reviews/{made['id']}/comments")
        comment_ids.update({row["id"]: new["id"] for row, new in zip(inline, listed, strict=False)})
    for reply in [row for row in recorded["review_comments"] if row.get("in_reply_to_id")]:
        parent = comment_ids.get(reply["in_reply_to_id"])
        if parent is not None:
            made = _http("POST", f"{api}/pulls/{number}/comments/{parent}/replies",
                         {"body": sha(reply.get("body") or "")})
            comment_ids[reply["id"]] = made["id"]
    for status in recorded["statuses"]:
        target = shas.get(status["sha"]) or (commits[-1] if commits else "")
        if not target:
            continue
        _http("POST", f"{api}/statuses/{target}", {key: sha(str(status.get(key) or "")) for key in
                                                    ("state", "context", "description", "target_url")})
    return _pull_pairs(recorded, number, shas)


_PR_NUMBER_KEYS = ("pr_id", "pr_number")


def renumber(tables: dict[str, list[dict[str, Any]]], recorded: dict[str, Any],
             pairs: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """The rows with the pull request's number as the replay opened it: a link follows by its text (``pairs``),
    the number itself is a field (``pull_request.id``, a review's ``pr_id``) or the review run's title
    "Pull request #N:"."""
    old = str(recorded["pull"]["number"])
    link = f"{recorded['repository']}/pull/"
    new = next((value[len(link):] for key, value in pairs.items() if key == f"{link}{old}"), old)
    if new == old:
        return tables

    def fix(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {name: fix(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [fix(item) for item in value]
        if key in _PR_NUMBER_KEYS and str(value) == old:
            return type(value)(new) if isinstance(value, int) else new
        return value

    rows = {table: [fix(row) for row in items] for table, items in tables.items()}
    for run in rows.get("workflow_runs", []):
        pull = run.get("pull_request")
        if isinstance(pull, dict) and str(pull.get("id")) == old:
            run["pull_request"] = {**pull, "id": new}
        if isinstance(run.get("title"), str) and run["title"].startswith(f"Pull request #{old}:"):
            run["title"] = f"Pull request #{new}:" + run["title"][len(f"Pull request #{old}:"):]
    return rows


def _pull_pairs(recorded: dict[str, Any], number: int, shas: dict[str, str]) -> dict[str, str]:
    old = recorded["pull"]["number"]
    repository = recorded["repository"]
    pairs = {f"{repository}/pull/{old}": f"{repository}/pull/{number}",
             f"{repository}/pulls/{old}": f"{repository}/pulls/{number}"}
    pairs.update({key: value for key, value in shas.items() if key and value})
    pairs.update({key[:7]: value[:7] for key, value in shas.items() if key and value})
    return pairs


# ---- checks ----------------------------------------------------------------------------------------------------------

def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # a dataclass in the module looks itself up there
    spec.loader.exec_module(module)
    return module


def check(text: str) -> list[str]:
    """What keeps ``text`` (a bundle) out of the repository: its size, a secret, a device id, a private binding."""
    problems = []
    if len(text.encode()) > MAX_BYTES:
        problems.append(f"{len(text.encode())} bytes, more than {MAX_BYTES} (the scrub reads no bigger file)")
    patterns = _load_module(BACKEND / "scripts" / "secret_patterns.py", "bundle_secret_patterns")
    for pattern in patterns.compiled():
        if pattern.search(text):
            problems.append(f"a secret matches {pattern.pattern[:40]!r}")
    devices = sorted(set(_DEVICE_ID.findall(text)))
    if devices:
        problems.append(f"a recording device's id: {len(devices)} (export it again; only the placeholder may stay)")
    private = sorted(set(_PRIVATE_FIELD.findall(text)))
    if private:
        problems.append(f"a stack's private binding: {', '.join(private[:5])} (export it again)")
    return problems


def dumps(bundle: dict[str, Any]) -> str:
    """One JSON document, one table row per line (the scrub reports lines; a diff stays readable)."""
    return json.dumps(bundle, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


async def export(run_id: str, *, github: str = "", app_base: str = "") -> dict[str, Any]:
    from app.db import async_session_factory

    async with async_session_factory() as db:
        collected = await collect(db, run_id)
    main = next(row for row in collected["tables"]["workflow_runs"] if row["id"] == collected["main_run"])
    bundle = {"format": FORMAT, "version": VERSION, "sample": True, "id": str(uuid.uuid4()),
              "exported_at": datetime.now(UTC).isoformat(), **collected, "pull": None}
    if github and main.get("repository") and main.get("branch"):
        repository = str(main["repository"]).split(":", 1)[-1]
        bundle["pull"] = export_pull(github, repository, main["branch"])
    return sanitize(bundle, github=github, app_base=app_base)


# ---- import ----------------------------------------------------------------------------------------------------------

def _new_id(old: str) -> str:
    if _UUID.match(old):
        return str(uuid.uuid4())
    prefix = old.split("_", 1)[0] + "_" if "_" in old else ""
    size = max(len(old) - len(prefix), 8)
    return (prefix + secrets.token_hex(size))[:len(old)] if len(old) >= 8 else prefix + secrets.token_hex(4)


def _shift(tables: dict[str, list[dict[str, Any]]], main_run: str) -> timedelta:
    """How far every time moves so the main run ends now."""
    main = next(row for row in tables["workflow_runs"] if row["id"] == main_run)
    end = _decode(main.get("completed_at") or main.get("updated_at") or main.get("created_at"))
    return datetime.now(UTC).replace(tzinfo=None) - end if isinstance(end, datetime) else timedelta(0)


async def _targets(db: Any, models: dict[str, Any], bundle: dict[str, Any], workspace: str,
                   username: str) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models import FlowDefinition, FlowDefinitionVersion, Project, User, WorkItem
    project = (await db.execute(select(Project).where(Project.name == workspace))).scalars().first()
    if project is None:
        raise SystemExit(f"run_bundle: no Workspace '{workspace}' (run the demo seed first)")
    owner = (await db.execute(select(User).where(User.username == username))).scalars().first()
    if owner is None:
        raise SystemExit(f"run_bundle: no user '{username}'")
    users = {}
    for old, user in bundle["references"]["users"].items():
        found = None
        if user.get("account_type", "human") != "human":
            found = (await db.execute(select(User).where(User.username == user["username"]))).scalars().first()
        users[old] = (found or owner).id
    items = {}
    for old, item in bundle["references"]["work_items"].items():
        found = (await db.execute(select(WorkItem).where(WorkItem.project_id == project.id,
                                                         WorkItem.source_key == item.get("key")))).scalars().first()
        items[old] = found.id if found is not None else None
    versions = {}
    for old, version in bundle["references"]["flow_definition_versions"].items():
        found = (await db.execute(
            select(FlowDefinitionVersion).join(FlowDefinition, FlowDefinition.id == FlowDefinitionVersion.flow_id)
            .where(FlowDefinition.key == version.get("key"))
            .order_by((FlowDefinitionVersion.version == version.get("version")).desc(),
                      FlowDefinitionVersion.version.desc()))).scalars().first()
        versions[old] = found.id if found is not None else None
    return {"projects": project.id, "users": users, "owner": owner, "work_items": items,
            "flow_definition_versions": versions}


async def _placeholder_device(db: Any, models: dict[str, Any], owner: Any) -> str:
    """A revoked device for the seat's job: it shows the run's device, it can never pair or take a job."""
    from sqlalchemy import select

    from app.models import UserDevice

    found = (await db.execute(select(UserDevice).where(
        UserDevice.owner_user_id == owner.id, UserDevice.name == DEVICE_NAME,
        UserDevice.status == "revoked"))).scalars().first()
    if found is not None:
        return found.id
    now = datetime.now(UTC).replace(tzinfo=None)
    device = UserDevice(owner_user_id=owner.id, name=DEVICE_NAME, name_key="sample-device", os="linux",
                    public_key="sample-run-placeholder-not-a-key", folders=[], profiles=[], status="revoked",
                    revoked_at=now, revoke_reason="sample run placeholder", max_parallel_jobs=0)
    db.add(device)
    await db.flush()
    return device.id


async def already_imported(db: Any, bundle_id: str, project_id: str) -> bool:
    from sqlalchemy import select

    from app.models import WorkflowRun

    runs = (await db.execute(select(WorkflowRun).where(WorkflowRun.project_id == project_id,
                                                       WorkflowRun.title.startswith(TITLE_PREFIX)))).scalars()
    return any(dict(run.context or {}).get("sample_bundle") == bundle_id for run in runs)


async def import_bundle(bundle: dict[str, Any], *, workspace: str, github: str, app_base: str = "",
                        username: str = "admin", session_factory: Any = None) -> str | None:
    """Write ``bundle`` into ``workspace`` as a sample run; the new main run's id, ``None`` when already there."""
    require_demo()
    if bundle.get("format") != FORMAT or bundle.get("version") != VERSION or bundle.get("sample") is not True:
        raise SystemExit("run_bundle: not a sample run bundle of this version")
    if session_factory is None:
        from app.db import async_session_factory as session_factory
    models = _models()
    async with session_factory() as db:
        return await _import(db, models, bundle, workspace=workspace, github=github, app_base=app_base,
                             username=username)


async def _import(db: Any, models: dict[str, Any], bundle: dict[str, Any], *, workspace: str, github: str,
                  app_base: str, username: str) -> str | None:
    targets = await _targets(db, models, bundle, workspace, username)
    if await already_imported(db, bundle["id"], targets["projects"]):
        print("sample run: already imported")
        return None
    pairs = {GIT_BASE: github.rstrip("/"), APP_BASE: app_base.rstrip("/") or "http://127.0.0.1:8000"}
    ids: dict[str, dict[str, str]] = {table: {} for table in TABLES}
    for table in TABLES:
        for row in bundle["tables"].get(table, []):
            old = row.get(_pk(models[table]))
            if isinstance(old, str) and not _pk_is_fk(models[table]):
                ids[table][old] = _new_id(old)
    ids["turn_trace_summaries"] = dict(ids["turn_traces"])
    every = {old: new for table in ids.values() for old, new in table.items()}
    if bundle.get("pull"):
        # The pull request's text names the runs ("workflow run <id>", the bot's "Octryx run <id>"): their new ids.
        pairs.update(replay_pull(github, _walk(bundle["pull"], replacer({**pairs, **every}))))
        bundle = {**bundle, "tables": renumber(bundle["tables"], bundle["pull"], pairs)}
    device = None
    if bundle["tables"].get("device_jobs") or DEVICE_PLACEHOLDER in json.dumps(bundle["tables"]):
        device = await _placeholder_device(db, models, targets["owner"])
        pairs[DEVICE_PLACEHOLDER] = device
    change = replacer({**pairs, **every})
    delta = _shift(bundle["tables"], bundle["main_run"])
    main_new = ids["workflow_runs"][bundle["main_run"]]
    for table in TABLES:
        model = models[table]
        rows = _ordered(model, bundle["tables"].get(table, []))
        for row in rows:
            db.add(_build(model, row, table=table, ids=ids, targets=targets, device=device,
                          change=change, delta=delta, main=row.get("id") == bundle["main_run"],
                          bundle_id=bundle["id"]))
        await db.flush()
    await _record_pull_request(db, main_new, targets["owner"], (bundle.get("pull") or {}).get("pull") or {})
    await db.commit()
    print(f"sample run: imported as {main_new}")
    return main_new


async def _record_pull_request(db: Any, run_id: str, owner: Any, recorded: dict[str, Any]) -> None:
    """The run's internal pull request record, written the way a run's ``scm.open_pr`` writes it: the identity is
    derived once, stored on the run and on the record (``sync_pull_request``); the run detail shows the run's own."""
    from app.models import WorkflowRun
    from app.services.secure_work.pull_requests.pull_requests import sync_pull_request
    from app.services.secure_work.pull_requests.record_identity import pull_request_identity

    run = await db.get(WorkflowRun, run_id)
    pull = dict(run.pull_request or {}) if run is not None else {}
    if not (run and run.work_item_id and pull.get("id") and pull.get("url") and pull.get("repository")):
        return
    identity = pull_request_identity(pull.get("provider") or "github", pull["url"], pull["repository"], pull["id"])
    run.pull_request = {**pull, "identity": identity}
    await sync_pull_request(db, current_user=owner, workspace_id=run.project_id, payload={
        "work_item_id": run.work_item_id, "identity": identity,
        "pr_url": pull["url"], "title": recorded.get("title") or run.title,
        "source_branch": pull.get("branch") or run.branch, "status": pull.get("state") or "open",
        "reviewers": list(pull.get("reviewers") or [])})


def _pk(model: Any) -> str:
    return model.__table__.primary_key.columns.values()[0].name


def _pk_is_fk(model: Any) -> bool:
    return bool(model.__table__.primary_key.columns.values()[0].foreign_keys)


def _ordered(model: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parents before children for a table that refers to itself."""
    table = model.__table__
    own = [column.name for column in table.columns
           if any(fk.column.table is table for fk in column.foreign_keys)]
    if not own:
        return rows
    pk = _pk(model)
    known = {row[pk] for row in rows}
    placed, out, left = set(), [], list(rows)
    while left:
        ready = [row for row in left if all(row.get(name) in (None, *placed) or row.get(name) not in known
                                            for name in own)]
        if not ready:
            ready = left[:1]
        for row in ready:
            placed.add(row[pk])
            out.append(row)
        left = [row for row in left if row[pk] not in placed]
    return out


def _build(model: Any, row: dict[str, Any], *, table: str, ids: dict[str, dict[str, str]], targets: dict[str, Any],
           device: str | None, change, delta: timedelta, main: bool, bundle_id: str) -> Any:
    from sqlalchemy import DateTime

    columns = model.__table__.columns
    keys = _columns(model)
    item = model()
    pk = _pk(model)
    for name, column in columns.items():
        if name not in row or name not in keys:
            continue
        value = _decode(row[name])
        fks = list(column.foreign_keys)
        if fks:
            target = fks[0].column.table.name
            value = _reference(table, name, target, value, column.nullable, ids, targets, device)
        elif name == pk and isinstance(value, str):
            value = ids[table].get(value, value)
        elif name == pk:
            continue  # an integer key: the database counts it
        elif isinstance(column.type, DateTime) and isinstance(value, datetime):
            value = value + delta
        elif value is not None and not isinstance(value, (int, float, bool, Decimal, bytes)):
            value = _walk(value, change)
        setattr(item, keys[name], value)
    if table == "workflow_runs":
        if main and not str(item.title or "").startswith(TITLE_PREFIX):
            item.title = (TITLE_PREFIX + str(item.title or item.workflow_key))[:220]
        item.context = {**dict(item.context or {}), "sample_bundle": bundle_id}
    return item


def _reference(table: str, name: str, target: str, value: Any, nullable: bool, ids: dict[str, dict[str, str]],
               targets: dict[str, Any], device: str | None) -> Any:
    if value is None:
        return None
    if target in ids:
        new = ids[target].get(value)
    elif target == "users":
        new = targets["users"].get(value, targets["owner"].id)
    elif target == "projects":
        new = targets["projects"]
    elif target in ("work_items", "flow_definition_versions"):
        new = targets[target].get(value)
    elif target == "user_devices":
        new = device
    else:
        new = None
    if new is None and not nullable:
        raise SystemExit(f"run_bundle: {table}.{name} refers to {target} {value!r}, which this install lacks")
    return new


# ---- command line ----------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    out = commands.add_parser("export", help="one finished run to a bundle file")
    out.add_argument("--run", required=True)
    out.add_argument("--github", default="", help="the fake GitHub the run worked on (its pull request comes along)")
    out.add_argument("--app-base", default="", help="this stack's URL, replaced by a placeholder")
    out.add_argument("--out", required=True)
    checked = commands.add_parser("check", help="the size, secret, device and binding checks of a bundle file")
    checked.add_argument("file")
    into = commands.add_parser("import", help="a bundle file into the demo as a sample run (demo only)")
    into.add_argument("file")
    into.add_argument("--workspace", default="Demo Shop")
    into.add_argument("--github", default=f"http://127.0.0.1:{os.environ.get('OCTRYX_DEMO_GIT_PORT', '8434')}")
    into.add_argument("--app-base", default="")
    into.add_argument("--user", default="admin")
    args = parser.parse_args(argv)
    if args.command == "export":
        text = dumps(asyncio.run(export(args.run, github=args.github, app_base=args.app_base)))
        problems = check(text)
        if problems:
            print("run_bundle: refusing to write the bundle:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"run_bundle: wrote {args.out} ({len(text.encode())} bytes); check it in the repository: "
              f"run_bundle.py check {args.out}")
        return 0
    if args.command == "check":
        problems = check(Path(args.file).read_text(encoding="utf-8"))
        print("\n".join(problems) or "run_bundle: ok")
        return 1 if problems else 0
    require_demo()
    bundle = json.loads(Path(args.file).read_text(encoding="utf-8"))
    asyncio.run(import_bundle(bundle, workspace=args.workspace, github=args.github, app_base=args.app_base,
                              username=args.user))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(BACKEND))
    raise SystemExit(main())
