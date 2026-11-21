"""The hands-on scenarios run side by side, each worker on its own Playwright, results in the scenarios' order
(the web test's depth stays, its time goes; workers from the platform's data and the cores)."""

from __future__ import annotations

import contextlib
import sys
import threading
import time
import types

from octryx_claude import hands_on, hands_on_browser


def test_the_worker_count_follows_the_cores_and_the_data():
    data = {"cores_per_worker": 3, "max": 4}
    assert hands_on.worker_count(data, 10, cores=14) == 4
    assert hands_on.worker_count(data, 10, cores=8) == 2
    assert hands_on.worker_count(data, 2, cores=14) == 2  # never more workers than scenarios
    assert hands_on.worker_count(data, 10, cores=2) == 1
    assert hands_on.worker_count(None, 10, cores=14) == 1  # no workers in the platform's data: one at a time
    assert hands_on.worker_count({"cores_per_worker": 0, "max": 4}, 10, cores=14) == 1


def test_the_scenarios_run_side_by_side_and_report_in_their_order(monkeypatch, tmp_path):
    starts: list[int] = []

    @contextlib.contextmanager
    def fake_playwright():
        starts.append(threading.get_ident())  # one Playwright per worker thread
        yield object()

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = fake_playwright
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    threads: dict[str, int] = {}

    def scenario_run(_playwright, _channel, scenario, _url, _shots, _start=60, _settle=None):
        threads[scenario["id"]] = threading.get_ident()
        time.sleep(0.3)
        return {"id": scenario["id"], "passed": scenario["id"] != "s2", "screenshots": []}

    monkeypatch.setattr(hands_on_browser, "run_scenario", scenario_run)
    scenarios = [{"id": f"s{index}"} for index in range(4)]
    began = time.monotonic()
    results, problem = hands_on.run_scenarios(scenarios, "http://127.0.0.1:1/", None, tmp_path, workers=4)
    assert problem == "" and time.monotonic() - began < 1.2  # four 0.3 s at once (+ s2 alone), not 1.5 s
    assert [item["id"] for item in results] == ["s0", "s1", "s2", "s3"]
    assert [item["passed"] for item in results] == [True, True, False, True]
    assert len(set(threads.values())) >= 4 and len(starts) == 5  # four workers, then the red s2 once alone
    assert "parallel_interference" not in results[2]  # red alone too: really red

    starts.clear()
    results, _problem = hands_on.run_scenarios(scenarios, "http://127.0.0.1:1/", None, tmp_path)
    assert len(starts) == 1 and [item["id"] for item in results] == ["s0", "s1", "s2", "s3"]  # workers=1:


def test_a_missing_browser_in_any_worker_is_the_run_s_problem(monkeypatch, tmp_path):
    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = contextlib.nullcontext
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)

    def scenario_run(_playwright, _channel, scenario, _url, _shots, _start=60, _settle=None):
        if scenario["id"] == "s3":
            raise hands_on_browser.BrowserUnavailableError("install Chrome")
        return {"id": scenario["id"], "passed": True, "screenshots": []}

    monkeypatch.setattr(hands_on_browser, "run_scenario", scenario_run)
    results, problem = hands_on.run_scenarios([{"id": f"s{index}"} for index in range(4)], "u", None, tmp_path,
                                              workers=2)
    assert results == [] and problem


def test_two_scenarios_that_disturb_each_other_side_by_side_pass_alone_and_say_so(monkeypatch, tmp_path):
    """Red side by side runs once more alone before it is red; green alone is parallel
    interference (shared data), information for the team."""
    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = contextlib.nullcontext
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    shared = {"busy": 0}  # the app's one shared basket: two scenarios at once see each other's item
    lock = threading.Lock()

    def scenario_run(_playwright, _channel, scenario, _url, _shots, _start=60, _settle=None):
        with lock:
            shared["busy"] += 1
        time.sleep(0.2)
        with lock:
            crowded = shared["busy"] > 1
        time.sleep(0.05)
        with lock:
            shared["busy"] -= 1
        if scenario["id"] == "broken":
            return {"id": "broken", "passed": False, "error": "really red", "screenshots": []}
        return {"id": scenario["id"], "passed": not crowded, "error": "basket shows 2 items", "screenshots": []}

    monkeypatch.setattr(hands_on_browser, "run_scenario", scenario_run)
    scenarios = [{"id": "add"}, {"id": "remove"}, {"id": "broken"}]
    results, problem = hands_on.run_scenarios(scenarios, "u", None, tmp_path, workers=3)
    assert problem == ""
    assert [(item["id"], item["passed"], item.get("parallel_interference", False)) for item in results] == [
        ("add", True, True), ("remove", True, True), ("broken", False, False)]  # really red stays red


def test_a_repository_that_shares_data_runs_its_scenarios_one_at_a_time():
    from octryx_claude.environment_file import _serve

    errors: list[str] = []
    serve = _serve({"command": "npm start", "url": "http://127.0.0.1:3000/", "parallel": False}, errors)
    assert errors == [] and serve["parallel"] is False
    assert "parallel" not in _serve({"command": "npm start", "url": "http://127.0.0.1:3000/"}, [])
    _serve({"command": "npm start", "url": "http://127.0.0.1:3000/", "parallel": "no"}, errors)
    assert errors and "parallel" in errors[0]


def test_a_browser_that_does_not_start_in_time_is_unavailable_at_once(monkeypatch, tmp_path):
    """While the GoogleUpdater ran no Chrome started and the test waited for its command's timeout; the
    start limit (platform data) reports browser_unavailable with the remedy."""
    asked: list[float] = []

    class TimeoutError(Exception):  # noqa: A001 - Playwright's own class name, which the launcher recognises
        pass

    class Chromium:
        def launch_persistent_context(self, _profile, **options):
            asked.append(options["timeout"])
            raise TimeoutError("BrowserType.launch_persistent_context: Timeout 7000ms exceeded.")

    @contextlib.contextmanager
    def fake_playwright():
        yield types.SimpleNamespace(chromium=Chromium())

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = fake_playwright
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    scenario = {"id": "s0", "viewport": {"width": 390, "height": 844}, "steps": [{"do": "goto", "path": "/"}]}
    results, problem = hands_on.run_scenarios([scenario], "http://127.0.0.1:1/", "chrome", tmp_path, start_seconds=7)
    assert results == [] and asked == [7000]
    assert "did not start within 7 s" in problem and "chromium" in problem
