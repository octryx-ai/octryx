"""``run_python_probe`` fails on a stuck probe and waits for a slow one (see the helper)."""

from __future__ import annotations

import time

import pytest

from tests.fresh_interpreter_support import run_python_probe


def test_a_stuck_probe_fails_with_where_it_stopped():
    started = time.monotonic()
    with pytest.raises(AssertionError) as stuck:
        run_python_probe("import threading\nthreading.Event().wait()\n", stall_seconds=4)
    assert "made no progress for 4 s" in str(stuck.value) and "threading.py" in str(stuck.value)  # the wait inside Event.wait
    assert time.monotonic() - started < 60


def test_a_probe_that_keeps_moving_runs_past_the_stall_allowance_and_returns_its_output():
    # Like a slow import: a new module every second, for longer than the allowance.
    slow = ("import importlib, sys, time\n"
            "for name in ('csv', 'decimal', 'fractions', 'statistics', 'difflib', 'textwrap', 'zipfile'):\n"
            "    time.sleep(1)\n    importlib.import_module(name)\n"
            "print('done', sys.argv[1])\n")
    result = run_python_probe(slow, "x", stall_seconds=3)
    assert (result.returncode, result.stdout.strip()) == (0, "done x")
