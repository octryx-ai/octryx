"""Sandbox harness for the migration check of the local dev launcher (dev-start.sh).

A test runs a copy of the real dev-start.sh and its ownership module in a temporary checkout.
Its backend holds the real alembic.ini and alembic/env.py over a test-owned revision graph and a
scratch SQLite database. A minimal ``app`` package provides what env.py imports, before and after
the parity revisions: ``app.db.Base`` and ``app.models``, and ``app.db.migration_metadata``. Its
``app.config`` stands in for the real pydantic settings. The package must stay complete: a module
missing here would be looked up in the main checkout through the venv's editable install, or fail
env.py at import. Test doubles replace the tools the launcher runs:

- backend/.venv/bin/python records every call and runs the real interpreter. It refuses to run
  uvicorn or the launch helper, so no test can start a server, and it never lets pip run, so the
  real interpreter's packages stay untouched. FAKE_PYTHON_FAIL makes the call with exactly those
  arguments fail; FAKE_PYTHON_NOOP makes it exit 0 without doing anything.
- backend/.venv/bin/pip only records its calls, so nothing is installed.
- uv, first on PATH, answers ``--version`` with the pin dev-setup.sh requires and
  records every other call, so setup takes the uv on PATH: it never bootstraps a real uv with
  a networked pip install, and ``uv sync`` installs nothing. FAKE_UV_STATUS sets its exit status.
- npm, first on PATH, records its calls and fails. A run that passes the migration check therefore
  ends at the frontend build, which shows that the launch went on after the check.

The two dev port literals are swapped for free ephemeral ports, so the machine's real 8000/5173
are never inspected. The canary secrets below are planted in the settings, a revision, the
database and its URL; none may reach the terminal or any file a run leaves behind.
The secrets and the test doubles are defined in ``dev_launcher_migration_doubles_support``.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from tests.dev_launcher_migration_doubles_support import (
    APP_PACKAGE,
    FAKE_PYTHON,
    FAKE_UV,
    MIGRATION_GATE,
    RECORDING_TOOL,
    VENV_LIBRARY,
    revision,
)
from tests.dev_launcher_test_support import (
    BASH,
    LIBRARY,
    REPO_ROOT,
    free_port,
    make_checkout,
    pid_dir_entries,
    strip_ansi,
)


def _write_tool(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


class Sandbox:
    """A temporary checkout with the real launcher, Alembic setup and test doubles for its tools."""

    def __init__(self, root: Path) -> None:
        self.checkout = make_checkout(root)
        self.backend = self.checkout / "backend"
        self.versions = self.backend / "alembic" / "versions"
        self.database = self.checkout / "data" / "app.db"
        self.url = f"sqlite+aiosqlite:///{self.database}"
        self.record = self.checkout / "data" / "upgrades"
        self._calls = self.checkout / "calls"
        for directory in ("data", "calls", "fakebin", "home", "tmp", "frontend/chat/node_modules"):
            (self.checkout / directory).mkdir(parents=True)

        source = (REPO_ROOT / "dev-start.sh").read_text(encoding="utf-8")
        for port, label in ((8000, "backend"), (5173, "frontend")):
            literal = f'dev_require_port_free {port} "{label}"'
            assert source.count(literal) == 2, literal
            source = source.replace(literal, f'dev_require_port_free {free_port()} "{label}"')
        (self.checkout / "dev-start.sh").write_text(source, encoding="utf-8")
        (self.checkout / "scripts").mkdir()
        shutil.copy(LIBRARY, self.checkout / "scripts" / LIBRARY.name)
        shutil.copy(MIGRATION_GATE, self.checkout / "scripts" / MIGRATION_GATE.name)
        shutil.copy(REPO_ROOT / "dev-setup.sh", self.checkout / "dev-setup.sh")

        self.versions.mkdir(parents=True)
        shutil.copy(REPO_ROOT / "backend" / "alembic.ini", self.backend / "alembic.ini")
        shutil.copy(REPO_ROOT / "backend" / "alembic" / "env.py", self.backend / "alembic" / "env.py")
        for relative, module in APP_PACKAGE.items():
            target = self.backend / "app" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(module, encoding="utf-8")
        self.write_revision("r1_first", revision("r1", None))
        self.write_revision("r2_second", revision("r2", "r1"))

        venv_bin = self.backend / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (self.backend / ".venv" / "lib").mkdir()
        (self.backend / ".venv" / "lib" / "launcher_test_library.py").write_text(VENV_LIBRARY, encoding="utf-8")
        calls = str(self._calls)
        _write_tool(venv_bin / "python", FAKE_PYTHON.replace("CALLS", calls).replace("REAL_PYTHON", sys.executable))
        for path, status in ((venv_bin / "pip", "0"), (self.checkout / "fakebin" / "npm", "1")):
            recording = RECORDING_TOOL.replace("CALLS", calls).replace("NAME", path.name)
            _write_tool(path, recording.replace("STATUS", status))
        _write_tool(self.checkout / "fakebin" / "uv", FAKE_UV.replace("CALLS", calls))
        self.env = {
            "PATH": f"{self.checkout / 'fakebin'}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.checkout / "home"),
            "TMPDIR": str(self.checkout / "tmp"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "DEBUG": "true",
            "SANDBOX_DATABASE_URL": self.url,
            "SANDBOX_UPGRADE_RECORD": str(self.record),
        }

    def write_revision(self, name: str, source: str) -> None:
        (self.versions / f"{name}.py").write_text(source, encoding="utf-8")

    def let_npm_succeed(self) -> None:
        """Makes every npm call succeed, and `npm run build` produce the files the launcher checks.
        A start then goes on to launch the backend, which the python test double refuses: the
        launch it asked for is recorded, and nothing starts."""
        static = self.backend / "app" / "web" / "static" / "chat"
        _write_tool(
            self.checkout / "fakebin" / "npm",
            f'#!/bin/sh\nprintf \'%s\\n\' "$*" >>"{self._calls}/npm"\n'
            f'if [ "$*" = "run build" ]; then mkdir -p "{static}" '
            f'&& : >"{static}/index.html" && : >"{static}/admin-design-tokens.css"; fi\n',
        )

    def run(self, **env: str) -> subprocess.CompletedProcess[str]:
        """Runs the launcher copy; ``stdout`` holds everything it printed, ANSI colours removed."""
        return self._run("dev-start.sh", env)

    def run_setup(self, **env: str) -> subprocess.CompletedProcess[str]:
        """Runs the copy of dev-setup.sh the same way."""
        return self._run("dev-setup.sh", env)

    def _run(self, script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [BASH, str(self.checkout / script)],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            start_new_session=True,
        )
        return subprocess.CompletedProcess(result.args, result.returncode, strip_ansi(result.stdout + result.stderr))

    def python(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        """Runs the real interpreter in the backend directory, not through the launcher."""
        return subprocess.run(
            [sys.executable, *args],
            cwd=self.backend,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def alembic(self, *args: str) -> None:
        result = self.python("-m", "alembic", *args, DATABASE_URL=self.url)
        assert result.returncode == 0, result.stdout + result.stderr

    def calls(self, tool: str) -> list[str]:
        path = self._calls / tool
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def alembic_calls(self) -> list[str]:
        return [call for call in self.calls("python") if call.startswith("-m alembic")]

    def upgrades(self) -> list[str]:
        """The revisions whose upgrade() ran, in order."""
        return self.record.read_text(encoding="utf-8").splitlines() if self.record.exists() else []

    def revisions_in_database(self) -> list[str]:
        if not self.database.exists():
            return []
        with sqlite3.connect(self.database) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "alembic_version" not in tables:
                return []
            return sorted(row[0] for row in connection.execute("SELECT version_num FROM alembic_version"))

    def stamp_database(self, rev: str) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE alembic_version SET version_num = ?", (rev,))

    def files_containing(self, secret: str, *, prepared: tuple[Path, ...] = ()) -> list[str]:
        """Files a run left in the checkout that hold ``secret``: tool-call records, logs, pids,
        data and temp files. The sandbox sources (launcher copy, modules, app and Alembic code,
        test doubles) and files a test ``prepared`` with the secret on purpose are skipped.
        """
        sources = (
            "dev-start.sh",
            "dev-setup.sh",
            "scripts",
            "programs",
            "backend/app",
            "backend/alembic",
            "backend/alembic.ini",
        )
        skipped = (*(self.checkout / source for source in sources), self.backend / ".venv", *prepared)
        return [
            str(path.relative_to(self.checkout))
            for path in sorted(self.checkout.rglob("*"))
            if path.is_file()
            and not any(path.is_relative_to(skip) for skip in skipped)
            and secret.encode() in path.read_bytes()
        ]


def failing_revision_writing(
    *, fails: bool = False, header: str = "", body: str = ""
) -> Callable[[Sandbox], tuple[Path, ...]]:
    """Prepares a failing r3 whose module or upgrade() also writes to the output."""

    def prepare(sandbox: Sandbox) -> tuple[Path, ...]:
        sandbox.alembic("upgrade", "head")
        sandbox.write_revision("r3_fails", revision("r3", "r2", fails=fails, header=header, body=body))
        # A UTF-8 locale, where awk rejects invalid bytes with a message that quotes the input.
        sandbox.env["LANG"] = "en_US.UTF-8"
        return ()

    return prepare


def assert_nowhere(
    sandbox: Sandbox, result: subprocess.CompletedProcess[str], text: str, *, prepared: tuple[Path, ...] = ()
) -> None:
    """Neither the terminal, nor a recorded tool call, nor any file the run left holds ``text``."""
    assert text not in result.stdout
    assert [call for tool in ("python", "pip", "npm") for call in sandbox.calls(tool) if text in call] == []
    assert sandbox.files_containing(text, prepared=prepared) == []


def launches(sandbox: Sandbox) -> list[str]:
    """Recorded python calls that start a server: uvicorn itself, or the detached-launch helper."""
    return [call for call in sandbox.calls("python") if " -m uvicorn " in f" {call} " or call.startswith("- ")]


def assert_nothing_started(sandbox: Sandbox) -> None:
    assert launches(sandbox) == []
    # A start installs nothing: neither pip nor uv is called, npm only builds.
    assert sandbox.calls("pip") == [] and sandbox.calls("uv") == []
    assert [call for call in sandbox.calls("npm") if call != "run build"] == []
    assert pid_dir_entries(sandbox.checkout) == []
    # Nothing was logged either: no server log, and the migration check keeps no output.
    assert list((sandbox.checkout / "logs").iterdir()) == []


def assert_went_on_to_the_frontend_build(sandbox: Sandbox, result: subprocess.CompletedProcess[str]) -> None:
    """The migration check passed: the launch went on and ended at the npm test double."""
    assert result.returncode == 1, result.stdout
    assert "Frontend build did not produce" in result.stdout
    assert sandbox.calls("npm") == ["run build"]
    assert_nothing_started(sandbox)


def assert_stopped_by_the_migration_check(
    sandbox: Sandbox, result: subprocess.CompletedProcess[str], reason: str
) -> None:
    assert result.returncode == 1, result.stdout
    assert reason in result.stdout
    assert "The backend and frontend were not started." in result.stdout
    # No raw tool output reaches the terminal: it can carry setting values and SQL parameters.
    assert "Traceback" not in result.stdout
    assert "INFO  [alembic" not in result.stdout
    # Nor diagnostics of the parsing tools, which can quote the input they choke on.
    assert not re.search(r"^(awk|sed|tr|sort): ", result.stdout, re.MULTILINE), result.stdout
    assert sandbox.calls("npm") == []
    assert_nothing_started(sandbox)
