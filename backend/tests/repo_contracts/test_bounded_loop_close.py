from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.support.loop_teardown import cancel_leftover_tasks, fail_on_survivors

BACKEND = Path(__file__).resolve().parents[2]
# The stall of 27.11.: one request of a gather fails the test while its sibling sits in a BaseHTTPMiddleware
# call_next and does not end on cancel.
FAILING_REQUEST_TEST = '''
import asyncio
import contextlib

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route

import tests.support.loop_teardown as loop_teardown

loop_teardown.LEFTOVER_TIMEOUT_S = 0.2


class Passthrough(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


async def fail(request):
    raise RuntimeError("the failing request")


async def stuck(request):
    while True:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(3600)


APP = Starlette(routes=[Route("/fail", fail), Route("/stuck", stuck)], middleware=[Middleware(Passthrough)])


@pytest.mark.asyncio
async def test_a_request_test_that_fails():
    async with AsyncClient(transport=ASGITransport(app=APP), base_url="http://harness.test") as client:
        await asyncio.gather(client.get("/stuck"), client.get("/fail"))
'''


def _inner_pytest(tmp_path: Path, *plugins: str, timeout: float) -> subprocess.CompletedProcess[str]:
    (tmp_path / "test_inner.py").write_text(FAILING_REQUEST_TEST, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    arguments = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path),
                 "-c", os.devnull, *(option for plugin in plugins for option in ("-p", plugin)), "test_inner.py"]
    return subprocess.run(arguments, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=timeout,
                          check=False)


def test_mutation_without_the_bounded_close_the_failed_request_test_stalls(tmp_path: Path) -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        _inner_pytest(tmp_path, timeout=8)


def test_mutation_a_failed_request_test_with_a_stuck_call_next_task_ends_in_bounded_time(tmp_path: Path) -> None:
    started = time.monotonic()
    result = _inner_pytest(tmp_path, "tests.support.loop_teardown", timeout=60)
    assert time.monotonic() - started < 30
    assert "1 failed, 1 error" in result.stdout, result.stdout + result.stderr
    assert "the failing request" in result.stdout
    assert "outlived the test and ignored cancel for 0.2 s" in result.stdout


def test_a_leftover_task_that_ends_on_cancel_is_cancelled_and_not_reported() -> None:
    async def leave_a_task() -> tuple[list[str], asyncio.Task]:
        task = asyncio.create_task(asyncio.sleep(3600))
        await asyncio.sleep(0)
        return await cancel_leftover_tasks(timeout=1), task

    survivors, task = asyncio.run(leave_a_task())
    assert survivors == [] and task.cancelled()
    fail_on_survivors()


# The bound rests on a private asyncio helper; a Python upgrade that drops it or stops it from hiding a task from
# all_tasks() must fail here, not leave the harness without its bound.
def test_the_private_asyncio_helper_the_bound_rests_on_still_hides_a_task_from_the_loop_close() -> None:
    assert callable(getattr(asyncio.tasks, "_unregister_task", None))

    async def hidden() -> bool:
        task = asyncio.create_task(asyncio.sleep(3600))
        await asyncio.sleep(0)
        asyncio.tasks._unregister_task(task)
        unseen = task not in asyncio.all_tasks()
        task.cancel()
        return unseen

    assert asyncio.run(hidden())
