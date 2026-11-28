from __future__ import annotations

import asyncio
import asyncio.tasks
import io

import pytest
import pytest_asyncio

LEFTOVER_TIMEOUT_S = 10.0
_SURVIVORS: list[str] = []


def _described(task: asyncio.Task) -> str:
    stack = io.StringIO()
    task.print_stack(limit=3, file=stack)
    return f"{task.get_name()} ({task.get_coro()!r}):\n{stack.getvalue().rstrip()}"


# A failed request test can leave tasks behind (a gather sibling, a BaseHTTPMiddleware call_next child) that do not
# end on cancel; the runner's loop close cancels and then waits for them without a bound, so the worker stalls.
async def cancel_leftover_tasks(timeout: float | None = None) -> list[str]:
    current = asyncio.current_task()
    leftover = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
    for task in leftover:
        task.cancel()
    if not leftover:
        return []
    _done, survivors = await asyncio.wait(leftover, timeout=LEFTOVER_TIMEOUT_S if timeout is None else timeout)
    for task in survivors:
        # Out of all_tasks(), so the loop close no longer waits for it; it is reported instead.
        asyncio.tasks._unregister_task(task)
    found = sorted(_described(task) for task in survivors)
    _SURVIVORS.extend(found)
    return found


def fail_on_survivors() -> None:
    survivors = list(_SURVIVORS)
    _SURVIVORS.clear()
    if survivors:
        pytest.fail(f"{len(survivors)} task(s) outlived the test and ignored cancel for {LEFTOVER_TIMEOUT_S:g} s:\n"
                    + "\n".join(survivors), pytrace=False)


# Torn down after every other fixture of the test, just before its loop closes.
@pytest_asyncio.fixture
async def _bounded_loop_close():
    yield
    await cancel_leftover_tasks()
    fail_on_survivors()


# The sync part also reports what the committed-database restore found for a test without a loop of its own.
@pytest.fixture(autouse=True)
def _no_task_outlives_its_test(request):
    _SURVIVORS.clear()
    if request.node.get_closest_marker("asyncio") is not None:
        request.getfixturevalue("_bounded_loop_close")
    yield
    fail_on_survivors()
