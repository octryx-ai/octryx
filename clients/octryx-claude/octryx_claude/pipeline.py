"""The run's CI pipeline on this device: the repository's declared commands, run before any agent starts."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from .pipeline_commands import (
    run_commands,
)
from .pipeline_env_file import _pointer, _repository_files, from_file, ready_folder
from .pipeline_green import _head, green_before, remember_green, tree_digest
from .pipeline_texts import file_summary, red_summary, style_summary, text
from .platform import PlatformResult, SessionContext, call_control_plane
from .run_contract import remember
from .state import LocalState

SCREENSHOTS = ("test-reports", "screenshots")
REPORT_TIMEOUT = 120.0
# A report that cannot reach the platform (an API restart) is sent again for about three minutes.
REPORT_ATTEMPTS = 7
REPORT_RETRY_SECONDS = 30.0
RED_FILE = "pipeline-red.md"


def pending(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    view = (contract or {}).get("pipeline")
    return view if isinstance(view, dict) and (view.get("commands") or _pointer(view)) else None


def _upload_screens(post: Any, view: dict[str, Any], folder: Path, since: float) -> int:
    from . import screens

    contract = {"phase": {"capability_class": "change"},
                "run": {"entry": view.get("entry"), "current_node": {"id": view.get("node_id")}}}
    return screens.upload(post, contract, folder, since=since)


def _note_style_verdict(state: LocalState, context: SessionContext, body: Any) -> None:
    findings = style_summary(body)
    if state is None or context is None or not findings:
        return
    try:
        path = state.session_dir(context.session_key) / RED_FILE
        before = path.read_text(encoding="utf-8") if path.is_file() else ""
        path.write_text(f"{before}\n\nCode style (fix each finding exactly as named):\n{findings}".strip(),
                        encoding="utf-8")
    except (OSError, ValueError):
        return


def _report_unreachable(answer: Any) -> bool:
    return answer.outcome == "unreachable" or (answer.outcome == "refused" and answer.status_code in (502, 503, 504))


class ReportLostError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _note_red(state: LocalState, context: SessionContext, results: list[dict[str, Any]],
              account: dict[str, Any] | None = None, texts: dict[str, Any] | None = None) -> None:
    if state is None or context is None:
        return
    try:
        path = state.session_dir(context.session_key) / RED_FILE
        summary = file_summary(account, texts) or red_summary(results)
        if summary:  # the whole text the turn's prompt gets (``device_jobs.with_pipeline_red``)
            path.write_text(text(texts, "run.launcher.pipeline_red", summary=summary), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _account_report(account: dict[str, Any]) -> dict[str, Any]:
    keys = ("file", "app_folder", "state", "errors", "sha256", "environment", "commands", "setup")
    return {key: account[key] for key in keys if key in account}


class _Clock:
    def __init__(self) -> None:
        self.start = self.last = time.monotonic()
        self.laps: dict[str, float] = {}

    def lap(self, step: str) -> None:
        now = time.monotonic()
        self.laps[step] = round(self.laps.get(step, 0.0) + now - self.last, 2)
        self.last = now

    def totals(self) -> dict[str, float]:
        return {**self.laps, "total": round(time.monotonic() - self.start, 2)}


def _run_or_reuse(state: LocalState, context: SessionContext, view: dict[str, Any], root: Path, tree: str,
                  account: dict[str, Any] | None, workdir: Path, style: dict[str, Any], clock: _Clock, *,
                  http: Any) -> tuple[list[dict[str, Any]], dict[str, Any] | None, float]:
    results = green_before(state, root, tree, view) if view.get("commands") else None
    clock.lap("green_before")
    started = time.time()
    if results is None and account is not None and account["state"] == "ok":
        account = ready_folder(view, account, workdir)
    clock.lap("setup")
    if results is None and (account is None or account["state"] == "ok"):
        shutil.rmtree(workdir.joinpath(*SCREENSHOTS), ignore_errors=True)  # only this run's screenshots count
        results = run_commands(view, workdir, lambda: _style_gate(state, context, view, style, root, http=http))
        if account is not None:
            results = _repository_files(results, str(account["app_folder"]))
        try:
            remember_green(state, root, tree, view, results)
        except OSError:
            pass  # a run that is not remembered only runs again next time
    results = results or []
    clock.lap("commands")
    return results, account, started


def _report_body(view: dict[str, Any], root: Path, workdir: Path, tree: str, account: dict[str, Any] | None,
                 results: list[dict[str, Any]], proof: dict[str, Any] | None, style: dict[str, Any],
                 clock: _Clock) -> dict[str, Any]:
    from .build_cache import read_notes  # noqa: PLC0415

    return {"node_id": view.get("node_id"), "entry": view.get("entry"), "results": results,
            "timings": clock.totals(), **({"build_cache": notes} if (notes := read_notes(workdir)) else {}),
            **({"red_on_base": proof} if proof is not None else {}),
            # The tree the commands ran on: the server checks it against the change it holds and pushes only a tree
            # its pipeline ran green on.
            **({"tree": tree} if tree else {}),
            **({"head": head} if (head := _head(root)) else {}),
            **({"environment_file": _account_report(account)} if account else {}),
            # The whole change's counts against the run's base; the server judges the code style.
            **style["report"]}


def _post_report(state: LocalState, context: SessionContext, body: dict[str, Any], *, http: Any) -> Any:
    answer = None
    for attempt in range(REPORT_ATTEMPTS):
        if attempt:
            time.sleep(REPORT_RETRY_SECONDS)
        answer = call_control_plane(state, context, "POST", "/sessions/pipeline", http=http, timeout=REPORT_TIMEOUT,
                                    body=body, retry=True)
        if not _report_unreachable(answer):
            break
    return answer


def run_for_session(state: LocalState, context: SessionContext, contract: dict[str, Any] | None, folder: str, *,
                    http: Any) -> dict[str, Any] | None:
    view = pending(contract)
    if view is None:
        return contract
    root = Path(folder).resolve()
    style: dict[str, Any] = {}  # the change's style report, made once: before the system test (gate) or at the end
    clock = _Clock()  # seconds per step in the report
    tree = tree_digest(root)
    clock.lap("tree")
    account: dict[str, Any] | None = None
    workdir = root
    if _pointer(view):
        view, account, workdir = from_file(view, root)  # the app folder; nothing runs when the file is not ok
    results, account, started = _run_or_reuse(state, context, view, root, tree, account, workdir, style, clock,
                                              http=http)

    def post_screen(body: dict[str, Any]) -> PlatformResult:
        return call_control_plane(state, context, "POST", "/sessions/screenshots", http=http, timeout=REPORT_TIMEOUT,
                                  body=body)

    try:
        _upload_screens(post_screen, view, workdir, started)
    except Exception:  # noqa: BLE001 - screenshots are review evidence; the pipeline's result still goes up
        pass
    clock.lap("screenshots")
    _note_red(state, context, results, account, dict((contract or {}).get("prompt_texts") or {}))
    proof = _red_on_base(view, root, account)
    clock.lap("red_on_base")
    if "report" not in style:  # not asked before a system test: made now
        style["report"] = _style_report(root, view) if view.get("code_style") and view.get("base") else {}
    clock.lap("code_style")
    answer = _post_report(state, context, _report_body(view, root, workdir, tree, account, results, proof, style,
                                                       clock), http=http)
    if answer is None or answer.outcome != "ok":
        if answer is not None and _report_unreachable(answer):
            # A report lost in an API restart left the pipeline pending for good, and the job still said
            # "pipeline_done". The turn is handed back; the platform offers it once more.
            raise ReportLostError("pipeline_report_unreachable")
        return contract
    _note_style_verdict(state, context, answer.body)
    return remember(state, context.session_key, answer.body) or contract


__all__ = [
    "RED_FILE",
    "ReportLostError",
    "pending",
    "run_for_session",
]


def _red_on_base(view: dict[str, Any], root: Path, account: dict[str, Any] | None) -> dict[str, Any] | None:
    if not view.get("red_on_base"):
        return None
    from .red_on_base import run  # noqa: PLC0415

    ready = account is not None and account.get("state") == "ok"
    environment = dict(account["environment"]) if ready else {"path": list(view.get("path") or [])}
    try:
        return run(dict(view["red_on_base"]), root, str(account["app_folder"]) if ready else ".", environment,
                   list(view.get("commands") or []))
    except Exception as error:  # noqa: BLE001 - the platform keeps the pipeline red with the reason
        return {"reason": f"the base run failed: {type(error).__name__}"}


def _style_gate(state: LocalState, context: SessionContext, view: dict[str, Any], style: dict[str, Any], root: Path,
                *, http: Any) -> str:
    if not (view.get("code_style") and view.get("base")):
        return ""
    if "report" not in style:
        style["report"] = _style_report(root, view)
    report = style["report"]
    if not report:
        return ""
    try:
        answer = call_control_plane(state, context, "POST", "/sessions/pipeline/style", http=http,
                                    timeout=REPORT_TIMEOUT, body={"node_id": view.get("node_id"),
                                                                  "entry": view.get("entry"), **report})
    except Exception:  # noqa: BLE001 - no verdict: the system test runs
        return ""
    body = answer.body if answer is not None and answer.outcome == "ok" and isinstance(answer.body, dict) else {}
    if not body.get("blocking"):
        return ""
    return "; ".join(str(item) for item in list(body.get("errors") or [])[:3]) or "see the code style errors"


def _style_report(root: Path, view: dict[str, Any]) -> dict[str, Any]:
    from .contract_sizes import (
        line_floor,
        sizes,  # noqa: PLC0415
    )
    from .style_tools import run_tools  # noqa: PLC0415

    try:
        from .style_l10n import l10n_facts  # noqa: PLC0415

        counted = sizes(root, str(view["base"]), line_floor(view["code_style"]))
        changed = list(counted.get("files") or {})
        return {"sizes": counted, "style_tools": run_tools(root, dict(view["code_style"]), changed,
                                                           base=str(view["base"])),
                "l10n": l10n_facts(root, dict(view["code_style"]), str(view["base"]), changed)}
    except Exception:  # noqa: BLE001 - no counts is no style verdict; the pipeline's own result still goes up
        return {}
