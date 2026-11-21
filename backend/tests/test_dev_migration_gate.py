"""The migration gate module of the local dev launcher: scripts/dev-migration-gate.sh.

Its parsers decide which facts of Alembic's raw output may reach the terminal. These tests feed them
crafted output directly, without running Alembic: tracebacks of every shape, Alembic's "FAILED:"
messages, revision listings with stray output, and invalid bytes. The launcher tests in
``tests.test_dev_launcher_migrations``, ``tests.test_dev_launcher_migrations_settings`` and
``tests.test_dev_launcher_migrations_failures`` cover the gate end to end in a sandbox checkout.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.dev_launcher_test_support import BASH, LIBRARY, REPO_ROOT, requires_bash, strip_ansi

pytestmark = requires_bash

GATE = REPO_ROOT / "scripts" / "dev-migration-gate.sh"
TOKEN = "ghp_canary_91ab"
TRACEBACK = "Traceback (most recent call last):"


@pytest.fixture
def backend(tmp_path: Path) -> Path:
    """A backend directory, physical path, like the one the gate runs in."""
    (tmp_path / "backend").mkdir()
    return (tmp_path / "backend").resolve()


def run_gate(backend: Path, script: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Runs ``script`` in /bin/bash, in <backend>, with the ownership and gate modules sourced."""
    return subprocess.run(
        [BASH, "-c", f'set -u\nsource "$OWNERSHIP_MODULE"\nsource "$GATE_MODULE"\n{script}', "gate-test", *args],
        cwd=backend,
        env={
            "PATH": os.environ["PATH"],
            "OWNERSHIP_MODULE": str(LIBRARY),
            "GATE_MODULE": str(GATE),
            "BACKEND_DIR": str(backend),
            "VENV_DIR": str(backend / ".venv"),
            "DEV_LAUNCHER_TAG": "test",
            **env,
        },
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
        check=False,
    )


def frame(backend: Path | str, relative: str, line: int, function: str | None = "upgrade") -> str:
    where = f'  File "{backend}/{relative}", line {line}'
    return where if function is None else f"{where}, in {function}"


def failure_cause(backend: Path, *lines: str, **env: str) -> str:
    result = run_gate(backend, 'alembic_failure_cause "$1"', "\n".join(lines), **env)
    assert result.returncode == 0, result.stderr
    # The parsing tools never speak: their diagnostics can quote the input.
    assert result.stderr == ""
    return result.stdout.rstrip("\n")


def test_revision_frame_names_the_failing_step(backend: Path) -> None:
    library = frame("/usr/lib/python3.12/site-packages", "alembic/command.py", 483, "upgrade")
    assert (
        failure_cause(
            backend,
            TRACEBACK,
            library,
            frame(backend, "alembic/env.py", 62, "do_run_migrations"),
            frame(backend, "alembic/versions/r3.py", 4),
            '    raise RuntimeError("boom")',
            f"RuntimeError: boom {TOKEN}",
        )
        == "RuntimeError at alembic/versions/r3.py:4 (in upgrade)"
    )


def test_innermost_project_frame_without_a_revision_frame(backend: Path) -> None:
    lines = [
        TRACEBACK,
        frame(backend, "alembic/env.py", 76, "run_async_migrations"),
        frame("/usr/lib/python3.12/site-packages", "asyncpg/connect_utils.py", 900, "_connect"),
        f"ConnectionRefusedError: [Errno 61] refused {TOKEN}",
    ]
    assert failure_cause(backend, *lines) == "ConnectionRefusedError at alembic/env.py:76 (in run_async_migrations)"


# lines after the traceback header -> expected cause; TOKEN must never be part of a cause.
CAUSES = {
    "venv and site-packages frames are no project frames": (
        [
            frame("BACKEND", ".venv/lib/python3.12/site-packages/x.py", 3, "f"),
            frame("BACKEND", "vendor/site-packages/y.py", 5, "g"),
            f"ImportError: {TOKEN}",
        ],
        "ImportError",
    ),
    "frames outside the backend are not named": (
        ['  File "/elsewhere/x.py", line 1, in f', f"OSError: {TOKEN}"],
        "OSError",
    ),
    "syntax error frame without a function": (
        [
            frame("BACKEND", "alembic/versions/r3.py", 6, None),
            "    def upgrade(:",
            "               ^",
            "SyntaxError: x",
        ],
        "SyntaxError at alembic/versions/r3.py:6",
    ),
    "path outside the narrow character set": (
        [frame("BACKEND", "alembic/versions/r3 x.py", 2), "RuntimeError: x"],
        "RuntimeError",
    ),
    "function name outside the narrow character set": (
        [frame("BACKEND", "alembic/versions/r3.py", 2, "upgräde"), "RuntimeError: x"],
        "RuntimeError at alembic/versions/r3.py:2",
    ),
    "local class with a message over two lines": (
        [frame("BACKEND", "alembic/versions/r3.py", 4), "r3_py.upgrade.<locals>.DataError: row", TOKEN],
        "r3_py.upgrade.<locals>.DataError at alembic/versions/r3.py:4 (in upgrade)",
    ),
    "colored exception line": (
        [frame("BACKEND", "alembic/versions/r3.py", 4), "\x1b[1;35mRuntimeError\x1b[0m: x", TOKEN],
        "",
    ),
    "non-ASCII class name": ([frame("BACKEND", "alembic/versions/r3.py", 4), "Fehlerä: x", TOKEN], ""),
    "carriage return in the class line": (
        [frame("BACKEND", "alembic/versions/r3.py", 4), f"RuntimeError\r: {TOKEN}"],
        "",
    ),
    "class name too long": ([frame("BACKEND", "alembic/versions/r3.py", 4), "A" * 200 + ": x"], ""),
    "chained exceptions: the last one counts": (
        [
            frame("BACKEND", "alembic/versions/r3.py", 4),
            f"KeyError: '{TOKEN}'",
            "",
            "During handling of the above exception, another exception occurred:",
            "",
            TRACEBACK,
            frame("BACKEND", "alembic/versions/r3.py", 7),
            "RuntimeError: y",
        ],
        "RuntimeError at alembic/versions/r3.py:7 (in upgrade)",
    ),
}


@pytest.mark.parametrize("case", list(CAUSES))
def test_failure_cause_holds_only_narrow_facts(backend: Path, case: str) -> None:
    lines, expected = CAUSES[case]
    lines = [line.replace("BACKEND", str(backend)) for line in lines]

    cause = failure_cause(backend, TRACEBACK, *lines)

    assert cause == expected
    assert TOKEN not in cause


def test_exception_group_names_no_cause(backend: Path) -> None:
    lines = [
        "  + Exception Group Traceback (most recent call last):",
        f'  |   File "{backend}/alembic/versions/r3.py", line 4, in upgrade',
        "  | ExceptionGroup: g (1 sub-exception)",
        "  +-+---------------- 1 ----------------",
        f"    | RuntimeError: {TOKEN}",
    ]
    assert failure_cause(backend, *lines) == ""


@pytest.mark.parametrize(
    ("failed", "expected"),
    [
        (
            "Can't locate revision identified by 'zz9'",
            "CommandError: revision zz9 is not in the revision graph of this checkout",
        ),
        (f"Multiple head revisions are present {TOKEN}", "CommandError"),
        (f"Can't locate revision identified by 'sk-{TOKEN}'", "CommandError"),
        ("Can't locate revision identified by '" + "a" * 33 + "'", "CommandError"),
        (f"Can't locate revision identified by 'zz9' {TOKEN}", "CommandError"),
    ],
    ids=["known shape", "other message", "revision that is no token", "revision over 32 characters", "trailing text"],
)
def test_command_error_never_mirrors_its_message(backend: Path, failed: str, expected: str) -> None:
    assert failure_cause(backend, f"@FAILED: {failed}") == expected


def test_traceback_wins_over_a_printed_failed_line(backend: Path) -> None:
    lines = [f"@FAILED: decoy {TOKEN}", TRACEBACK, frame(backend, "alembic/versions/r3.py", 4), "RuntimeError: x"]
    assert failure_cause(backend, *lines) == "RuntimeError at alembic/versions/r3.py:4 (in upgrade)"


def test_invalid_bytes_do_not_make_the_parsers_speak(backend: Path) -> None:
    # os.fsdecode keeps the invalid bytes as surrogates, which reach bash as the raw bytes again.
    invalid = os.fsdecode(b"\xff\xfe ") + TOKEN
    lines = [invalid, TRACEBACK, frame(backend, "alembic/versions/r3.py", 4), f"RuntimeError: {invalid}"]

    assert failure_cause(backend, *lines, LANG="en_US.UTF-8") == "RuntimeError at alembic/versions/r3.py:4 (in upgrade)"
    listing = run_gate(backend, 'migration_revisions "$1" current', f"@r2 (head)\n@{invalid}", LANG="en_US.UTF-8")
    assert (listing.stdout, listing.stderr) == ("r2", "")


LISTING = "\n".join(
    [
        "@r2 (head)",
        "@r1",
        f"@{TOKEN} printed by a revision",
        f"@{TOKEN}",
        "@r3 (effective head)",
        "@r2.b (head) (branchpoint)",
        "INFO  [alembic.runtime.migration] Context impl SQLiteImpl.",
    ]
)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("heads", "r2 r2.b r3"), ("current", f"{TOKEN} r1 r2 r2.b r3")],
)
def test_revision_listings_count_only_listing_lines(backend: Path, kind: str, expected: str) -> None:
    # Heads need Alembic's head mark; a bare token is indistinguishable from a current revision.
    result = run_gate(backend, 'migration_revisions "$1" "$2"', LISTING, kind)

    assert (result.stdout, result.stderr) == (expected, "")


def test_shown_revisions_mask_what_is_no_short_token(backend: Path) -> None:
    result = run_gate(backend, 'shown_revisions "$1"', "r2 r2.b " + "x" * 33 + " tok_1")

    assert result.stdout == "r2 ? ? tok_1"


@pytest.mark.parametrize(
    ("files", "holds_scripts"),
    [((), False), (("__init__.py",), False), (("__init__.py", "r1_first.py"), True), (None, False)],
    ids=["empty", "package marker only", "a revision script", "missing directory"],
)
def test_revision_scripts_are_told_apart_from_an_empty_directory(
    backend: Path, files: tuple[str, ...] | None, holds_scripts: bool
) -> None:
    versions = backend / "versions"
    if files is not None:
        versions.mkdir()
        for name in files:
            (versions / name).write_text("", encoding="utf-8")

    result = run_gate(backend, 'has_revision_scripts "$1"', str(versions))

    assert result.returncode == (0 if holds_scripts else 1)


@pytest.mark.parametrize("breakage", ["missing", "crlf", "empty"])
def test_launcher_names_a_gate_module_it_cannot_load(tmp_path: Path, breakage: str) -> None:
    # Loaded like the ownership module: bash 3.2 under set -e would exit without a word. An empty
    # module sources cleanly, so the launcher also checks that the gate is defined.
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO_ROOT / "dev-start.sh", tmp_path / "dev-start.sh")
    shutil.copy(LIBRARY, tmp_path / "scripts" / LIBRARY.name)
    if breakage == "crlf":
        (tmp_path / "scripts" / GATE.name).write_bytes(GATE.read_bytes().replace(b"\n", b"\r\n"))
    elif breakage == "empty":
        (tmp_path / "scripts" / GATE.name).write_text("", encoding="utf-8")

    result = subprocess.run(
        [BASH, str(tmp_path / "dev-start.sh")],
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    output = strip_ansi(result.stdout + result.stderr)

    assert result.returncode == 1, output
    assert "Could not load scripts/dev-migration-gate.sh (see the error above)" in output
    assert "Stopping dev servers" not in output
