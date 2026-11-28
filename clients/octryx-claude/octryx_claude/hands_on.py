"""The run's hands-on test on the device: start the built app, run the platform's scenarios in Chrome outside
Claude Code's sandbox and report each scenario's result with its screenshots."""

from __future__ import annotations

import base64
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from .hands_on_app import (
    BROWSER_UNAVAILABLE,
    DEVICE_BUSY,
    ENV_FILE_INVALID,
    ENV_SETUP_FAILED,
    LAST_END,
    LOCK_WAIT_SECONDS,
    PORT_IN_USE,
    SERVE_MISSING,
    _answers,
    _step,
    app_problem_code,
    reap_orphan,
    start_app,
    stop_app,
    url_lock,
)
from .platform import SessionContext, call_control_plane
from .run_contract import remember
from .state import LocalState

REPORT_TIMEOUT = 120.0
SERVE_HINT = ("The environment file declares a UI (system_test or browser) but no \"serve\": add {\"serve\": "
              "{\"command\": \"<starts the built app and keeps running>\", \"url\": \"http://127.0.0.1:<port>/\"}} so "
              "the platform can use the app; for a Flutter app e.g. \"flutter build web && python3 -m http.server "
              "8080 --bind 127.0.0.1 --directory build/web\".")


def pending(contract: dict[str, Any] | None) -> dict[str, Any] | None:
    view = (contract or {}).get("hands_on")
    if not isinstance(view, dict):
        return None
    return view if view.get("scenarios") or view.get("mode") == "reproduce" else None



def worker_count(workers: dict[str, Any] | None, scenarios: int, cores: int | None = None) -> int:
    settings = dict(workers or {})
    per, most = settings.get("cores_per_worker"), settings.get("max")
    if not (type(per) is int and per >= 1 and type(most) is int and most >= 1):
        return 1
    return max(1, min(most, scenarios, (cores or os.cpu_count() or 1) // per))


def run_scenarios(scenarios: list[dict[str, Any]], base_url: str, channel: str | None, shots: Path,
                  budget: float = 0, workers: int = 1, start_seconds: int = 0,
                  settle: dict[str, int] | None = None) -> tuple[list[dict[str, Any]], str]:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401, PLC0415
    except ImportError:
        from .hands_on_browser import PLAYWRIGHT_HINT  # noqa: PLC0415

        return [], PLAYWRIGHT_HINT
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    started = time.monotonic()
    count = max(1, min(workers, len(scenarios)))
    shares = [list(range(index, len(scenarios), count)) for index in range(count)]
    results: dict[int, dict[str, Any]] = {}
    problems: list[str] = []
    with ThreadPoolExecutor(max_workers=count) as pool:
        for found, problem in pool.map(lambda share: _run_share(scenarios, share, base_url, channel, shots, budget,
                                                                started, start_seconds, settle), shares):
            results.update(found)
            if problem:
                problems.append(problem)
    if problems:
        return [], problems[0]
    ordered = [results[index] for index in range(len(scenarios))]
    failed = [index for index, item in enumerate(ordered) if not item.get("passed")]
    if count > 1 and failed:
        # A scenario red side by side runs once more alone before it is red; green alone is
        # parallel interference (scenarios sharing the app's data), reported as information, never as red.
        again, problem = _run_share(scenarios, failed, base_url, channel, shots, 0, started, start_seconds, settle)
        if problem:
            return [], problem
        for index in failed:
            if again[index].get("passed"):
                ordered[index] = {**again[index], "parallel_interference": True}
            else:
                ordered[index] = again[index]
    return ordered, ""


# Playwright's sync API belongs to the thread that started it.
def _run_share(scenarios: list[dict[str, Any]], share: list[int], base_url: str, channel: str | None, shots: Path,
               budget: float, started: float, start_seconds: int = 0,
               settle: dict[str, int] | None = None) -> tuple[dict[int, dict[str, Any]], str]:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    from .hands_on_browser import START_SECONDS, BrowserUnavailableError, run_scenario  # noqa: PLC0415

    found: dict[int, dict[str, Any]] = {}
    with sync_playwright() as playwright:
        for index in share:
            scenario = scenarios[index]
            if budget and time.monotonic() - started > budget * 2:
                # Twice the budget: the rest is reported as not run (red), never silently dropped.
                found[index] = {"id": scenario["id"], "passed": False, "error": "not run: over twice the time "
                                f"budget of {int(budget)} s", "screenshots": []}
                continue
            try:
                found[index] = run_scenario(playwright, channel, scenario, base_url, shots,
                                            start_seconds or START_SECONDS, settle)
            except BrowserUnavailableError as missing:
                return {}, missing.hint
    return found, ""


def _declared_ui(view: dict[str, Any], root: Path, body: dict[str, Any]) -> dict[str, Any]:
    from . import environment_file  # noqa: PLC0415

    pointer = view.get("environment_file") if isinstance(view.get("environment_file"), dict) else {}
    account = environment_file.resolve(root, str(pointer.get("file") or ""), view.get("environment_pin"))
    if account["state"] != environment_file.OK:
        return {**body, "state": "unavailable", "code": ENV_FILE_INVALID,
                "problem": "the environment file is not usable: "
                + "; ".join(account.get("errors") or [account["state"]])}
    environment = account["environment"]
    serve = environment.get("serve")
    if not serve:
        if environment.get("system_test") or environment.get("browser"):
            return {**body, "state": "unavailable", "code": SERVE_MISSING, "problem": SERVE_HINT}
        return {**body, "state": "skipped", "reason": "the environment file declares no UI"}
    return {"environment": environment, "serve": serve, "folder": environment_file.folder_of(root, account)}


def _url_refusal(body: dict[str, Any], url: str, locked: bool) -> dict[str, Any] | None:
    if not locked:
        return {**body, "state": "unavailable", "code": DEVICE_BUSY,
                "problem": f"another hands-on test on this device kept "
                f"{url} for {LOCK_WAIT_SECONDS // 60} minutes"}
    if _answers(url) and reap_orphan(url):
        time.sleep(1)  # the port is free again once the group is gone
    if _answers(url):
        from .hands_on_port import holder  # noqa: PLC0415 - finding 30: name the process holding the port

        used = holder(url)
        return {**body, "state": "unavailable", "code": PORT_IN_USE,
                "problem": f"something else already answers on {url}"
                f"{f' ({used})' if used else ''}; the hands-on test only uses the app it started (stop the other "
                "server or change the port)"}
    return None


def _run_pass(view: dict[str, Any], serve: dict[str, Any], process: Any, scenarios: list[dict[str, Any]],
              channel: str | None, shots: Path, budget: float, began: float) -> tuple[list[dict[str, Any]], str]:
    try:
        parallel = serve.get("parallel") is not False  # the repository's opt-out (environment file)
        return run_scenarios(scenarios, serve["url"], channel, shots, budget,
                             worker_count(view.get("workers"), len(scenarios)) if parallel else 1,
                             int(view.get("browser_start_seconds") or 0), dict(view.get("restart_settle") or {}))
    finally:
        LAST_END.clear()
        LAST_END.update(stop_app(process, serve["url"]))
        _step("scenarios ended", began, scenarios=len(scenarios))


def execute(view: dict[str, Any], root: Path) -> tuple[dict[str, Any], Path | None]:
    from . import environment_file  # noqa: PLC0415
    from .pipeline_commands import _env  # noqa: PLC0415

    body: dict[str, Any] = {"node_id": view.get("node_id"), "entry": view.get("entry")}
    declared = _declared_ui(view, root, body)
    if "state" in declared:
        return declared, None
    environment, serve, folder = declared["environment"], declared["serve"], declared["folder"]
    from . import hands_on_repo  # noqa: PLC0415

    reproduce = view.get("mode") == "reproduce"
    kept, broken = hands_on_repo.load(folder, bug_key=str(view.get("bug_key") or "") if reproduce else "")
    if reproduce and not kept and not broken:
        return {**body, "state": "no_scenarios"}, None
    scenarios = kept if reproduce else [*list(view.get("scenarios") or []), *kept]
    from .build_cache import shim_env  # noqa: PLC0415

    # The pipeline's web build of the same inputs is reused (stacks.json build_artifacts).
    env = shim_env(_env(folder, list(environment.get("path") or []), environment), view.get("build_artifacts"))
    began = time.monotonic()
    _step("setup started", began, node=view.get("node_id"), mode=view.get("mode") or "check")
    ready, log = environment_file.setup(folder, environment, env)
    _step("setup ended", began, ready=ready)
    if not ready:
        return {**body, "state": "unavailable", "code": ENV_SETUP_FAILED,
                "problem": "the environment's setup failed: " + str(log)[-1500:]}, None
    from .serve_port import on_free_port  # noqa: PLC0415

    serve, env = on_free_port(serve, env)  # parallel runs never share the declared port
    shots = Path(tempfile.mkdtemp(prefix="octryx-hands-on-shots-"))
    with url_lock(serve["url"]) as locked:
        _step("lock", began, url=serve["url"], held=locked)
        if refusal := _url_refusal(body, serve["url"], locked):
            return refusal, shots
        process, problem = start_app(serve, folder, env, shots / "serve.log")
        _step("app started", began, problem=bool(problem))
        if problem:
            return {**body, "state": "unavailable", "code": app_problem_code(problem), "problem": problem,
                    **({"serve_end": dict(LAST_END)} if LAST_END else {})}, shots
        started = time.monotonic()
        budget = float(view.get("budget_seconds") or 0)
        channel = None if environment.get("browser") == "chromium" else "chrome"
        results, problem = _run_pass(view, serve, process, scenarios, channel, shots, budget, began)
        if not problem and not reproduce:  # red regressions: also red on the base commit?
            from .hands_on_base import recheck  # noqa: PLC0415

            results = recheck(view, root, folder, scenarios, results, environment, channel, budget)
            _step("base recheck ended", began)
    if problem:
        return {**body, "state": "unavailable", "code": BROWSER_UNAVAILABLE, "problem": problem}, shots
    return {**body, "state": "ran", **({"serve_end": dict(LAST_END)} if LAST_END else {}),
            "scenarios": [*results, *broken],
            "seconds": round(time.monotonic() - started, 1),
            "repo_scenarios": [{"id": item["id"], "title": item["title"]} for item in kept]}, shots


def _upload(post: Any, view: dict[str, Any], shots: Path | None, body: dict[str, Any]) -> None:
    names = {name for item in body.get("scenarios") or [] for name in item.get("screenshots") or []}
    for name in sorted(names):
        path = (shots / name) if shots is not None else None
        if path is None or not path.is_file():
            continue
        post({"node_id": view.get("node_id"), "entry": view.get("entry"), "name": name,
              "data": base64.b64encode(path.read_bytes()).decode("ascii")})


def run_for_session(state: LocalState, context: SessionContext, contract: dict[str, Any] | None, folder: str, *,
                    http: Any) -> dict[str, Any] | None:
    view = pending(contract)
    if view is None:
        return contract
    body, shots = execute(view, Path(folder).resolve())
    from .build_cache import read_notes  # noqa: PLC0415

    pointer = view.get("environment_file") if isinstance(view.get("environment_file"), dict) else {}
    if notes := read_notes(Path(folder).resolve() / str(pointer.get("app_folder") or ".")):
        body = {**body, "build_cache": notes}
    from .red_on_base import for_view  # noqa: PLC0415

    proof = for_view(view, Path(folder).resolve())  # the reproduction's tests on the base commit, when asked
    if proof is not None:
        body = {**body, "red_on_base": proof}

    def post_screen(screen: dict[str, Any]) -> Any:
        return call_control_plane(state, context, "POST", "/sessions/screenshots", http=http, timeout=REPORT_TIMEOUT,
                                  body=screen)

    try:
        _upload(post_screen, view, shots, body)
    except Exception:  # noqa: BLE001 - screenshots are evidence; the result still goes up
        pass
    finally:
        if shots is not None:
            shutil.rmtree(shots, ignore_errors=True)
    answer = call_control_plane(state, context, "POST", "/sessions/hands_on", http=http, timeout=REPORT_TIMEOUT,
                                body=body, retry=True)
    if answer is None or answer.outcome != "ok":
        from .pipeline import ReportLostError  # noqa: PLC0415

        raise ReportLostError("hands_on_report_unreachable")
    return remember(state, context.session_key, answer.body) or contract


__all__ = [
    "SERVE_HINT",
    "execute",
    "pending",
    "run_for_session",
    "run_scenarios",
]
