"""How the local dev launcher starts: loopback bind, readiness checks, explicit setup.

A start binds the backend to 127.0.0.1 unless DEV_START_BACKEND_HOST opts into a wider IPv4 bind,
installs nothing, and stops before touching anything when the checkout is not prepared.
./dev-setup.sh prepares it explicitly. The runs use the sandbox checkout and test doubles of
``tests.dev_launcher_migration_support``. When a run gets as far as launching the backend, the
python test double refuses the launch and records what it was asked to run, so nothing starts.
"""

from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

import pytest

from tests.dev_launcher_migration_doubles_support import PINNED_UV_VERSION, requires_alembic
from tests.dev_launcher_migration_support import Sandbox, assert_nothing_started, launches
from tests.dev_launcher_test_support import pid_dir_entries, requires_process_tools

pytestmark = [requires_process_tools, requires_alembic]

VERSION_CHECK = "-c import sys; sys.exit(sys.version_info < (3, 12))"
IMPORT_CHECK = "-P -c import alembic, uvicorn"


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def locked_sync(sandbox: Sandbox) -> str:
    """The one exact install dev-setup.sh runs, with its default extras."""
    return f"sync --project {sandbox.backend} --locked --extra dev --extra knowledge"


def backend_launch(sandbox: Sandbox) -> str:
    """The one backend launch a run asked for, which the test double refused."""
    (launch,) = launches(sandbox)
    assert " -m uvicorn app.main:app " in launch
    assert pid_dir_entries(sandbox.checkout) == []
    assert not (sandbox.checkout / "logs" / "backend.log").exists()
    return launch


@pytest.mark.parametrize(
    ("host", "url_host", "warned"),
    [
        (None, "127.0.0.1", False),
        ("0.0.0.0", "127.0.0.1", True),
        ("192.168.10.20", "192.168.10.20", True),
        ("127.0.0.2", "127.0.0.2", False),
    ],
    ids=["default loopback", "all interfaces", "one address", "another loopback address"],
)
def test_backend_binds_to_loopback_unless_a_wider_bind_is_opted_into(
    sandbox: Sandbox, host: str | None, url_host: str, warned: bool
) -> None:
    sandbox.let_npm_succeed()

    result = sandbox.run() if host is None else sandbox.run(DEV_START_BACKEND_HOST=host)

    assert result.returncode == 1, result.stdout
    assert f" --host {host or '127.0.0.1'} --port 8000 " in backend_launch(sandbox)
    assert f"Starting backend on http://{url_host}:8000 (listening on {host or '127.0.0.1'})" in result.stdout
    assert ("other hosts can reach it" in result.stdout) == warned


@pytest.mark.parametrize(
    "host",
    ["localhost", "::", "256.1.1.1", "1.2.3", "1.2.3.4.5", "01.2.3.4", "127.0.0.1 --reload", "0.0.0.0;id"],
)
def test_invalid_bind_address_stops_the_launch_before_anything_else(sandbox: Sandbox, host: str) -> None:
    result = sandbox.run(DEV_START_BACKEND_HOST=host)

    assert result.returncode == 1, result.stdout
    assert "DEV_START_BACKEND_HOST must be 127.0.0.1 (the default), 0.0.0.0 or one IPv4 address" in result.stdout
    assert "Stopping dev servers" not in result.stdout
    assert sandbox.calls("python") == []


def _remove_venv(sandbox: Sandbox) -> dict[str, str]:
    shutil.rmtree(sandbox.backend / ".venv")
    return {}


def _remove_node_modules(sandbox: Sandbox) -> dict[str, str]:
    shutil.rmtree(sandbox.checkout / "frontend" / "chat" / "node_modules")
    return {}


UNREADY = {
    "no venv": (_remove_venv, "there is no backend venv at"),
    "old Python": (lambda sandbox: {"FAKE_PYTHON_FAIL": VERSION_CHECK}, "does not run Python 3.12 or newer"),
    "missing dependencies": (lambda sandbox: {"FAKE_PYTHON_FAIL": IMPORT_CHECK}, "cannot import alembic and uvicorn"),
    "no node_modules": (_remove_node_modules, "has no node_modules"),
}


@pytest.mark.parametrize("case", list(UNREADY))
def test_unprepared_checkout_stops_the_launch_with_guidance(sandbox: Sandbox, case: str) -> None:
    prepare, problem = UNREADY[case]
    env = prepare(sandbox)

    result = sandbox.run(**env)

    assert result.returncode == 1, result.stdout
    assert "Not ready to start: " in result.stdout and problem in result.stdout
    assert "Run ./dev-setup.sh, which installs what is missing" in result.stdout
    # Nothing was stopped, installed, migrated or started.
    assert "Stopping dev servers" not in result.stdout
    assert [call for call in sandbox.calls("python") if call not in (VERSION_CHECK, IMPORT_CHECK)] == []
    assert sandbox.calls("pip") == [] and sandbox.calls("npm") == []
    assert_nothing_started(sandbox)


def test_start_installs_nothing_and_leaves_the_venv_as_it_is(sandbox: Sandbox) -> None:
    venv = sandbox.backend / ".venv"
    before = {path: path.stat().st_mtime_ns for path in venv.rglob("*")}

    result = sandbox.run()

    assert "Database is at Alembic head r2" in result.stdout
    assert {path: path.stat().st_mtime_ns for path in venv.rglob("*")} == before
    assert [call for call in sandbox.calls("python") if " -m pip " in f" {call} "] == []
    assert sandbox.calls("pip") == [] and sandbox.calls("npm") == ["run build"]


def test_setup_installs_the_backend_and_missing_frontend_packages(sandbox: Sandbox) -> None:
    sandbox.let_npm_succeed()
    shutil.rmtree(sandbox.checkout / "frontend" / "chat" / "node_modules")

    result = sandbox.run_setup()

    assert result.returncode == 0, result.stdout
    # The backend closure is the lock, installed exactly by the pinned uv from PATH;
    # pip is never used and no uv is bootstrapped.
    assert f"Using uv {PINNED_UV_VERSION} from PATH" in result.stdout
    assert sandbox.calls("uv") == [locked_sync(sandbox)]
    assert [call for call in sandbox.calls("python") if " -m pip " in f" {call} "] == []
    assert sandbox.calls("pip") == []
    assert not (sandbox.checkout / ".tools").exists()
    assert sandbox.calls("npm") == ["ci"]
    assert "Setup done. Start with ./dev-start.sh." in result.stdout
    # Setup starts nothing.
    assert launches(sandbox) == [] and pid_dir_entries(sandbox.checkout) == []


def test_setup_leaves_installed_frontend_packages_alone(sandbox: Sandbox) -> None:
    sandbox.let_npm_succeed()

    result = sandbox.run_setup()

    assert result.returncode == 0, result.stdout
    assert "Frontend packages are installed; left as they are" in result.stdout
    assert sandbox.calls("npm") == []


def test_setup_never_deletes_an_old_venv(sandbox: Sandbox) -> None:
    result = sandbox.run_setup(FAKE_PYTHON_FAIL=VERSION_CHECK)

    assert result.returncode == 1, result.stdout
    assert "does not run Python 3.12 or newer. It is never deleted automatically" in result.stdout
    assert (sandbox.backend / ".venv" / "bin" / "python").exists()
    assert [call for call in sandbox.calls("python") if call.startswith("-m pip")] == []


def test_setup_names_a_half_created_venv(sandbox: Sandbox) -> None:
    (sandbox.backend / ".venv" / "bin" / "python").unlink()

    result = sandbox.run_setup()

    assert result.returncode == 1, result.stdout
    assert "has no bin/python (a half-created venv?). It is never deleted automatically" in result.stdout
    assert (sandbox.backend / ".venv").exists()


def _without_venv_but_an_interpreter(sandbox: Sandbox, tmp_path: Path) -> str:
    """Removes the venv and returns a test-double interpreter for DEV_SETUP_PYTHON. It records its
    calls, answers the version check with FAKE_SETUP_PYTHON_VERSION_STATUS, and lays out a venv
    whose python is the sandbox's python test double, so nothing is installed for real."""
    venv_python = tmp_path / "venv-python"
    shutil.copy(sandbox.backend / ".venv" / "bin" / "python", venv_python)
    shutil.rmtree(sandbox.backend / ".venv")
    interpreter = sandbox.checkout / "fakebin" / "setup-python"
    interpreter.write_text(
        f'#!/bin/sh\nprintf \'%s\\n\' "$*" >>"{sandbox.checkout / "calls" / "setup-python"}"\n'
        'if [ "$1" = "-c" ]; then exit "${FAKE_SETUP_PYTHON_VERSION_STATUS:-0}"; fi\n'
        f'mkdir -p "$3/bin" && cp "{venv_python}" "$3/bin/python"\n',
        encoding="utf-8",
    )
    interpreter.chmod(0o755)
    return str(interpreter)


def test_setup_creates_a_missing_venv_with_the_chosen_interpreter(sandbox: Sandbox, tmp_path: Path) -> None:
    sandbox.let_npm_succeed()
    interpreter = _without_venv_but_an_interpreter(sandbox, tmp_path)

    result = sandbox.run_setup(DEV_SETUP_PYTHON=interpreter)

    assert result.returncode == 0, result.stdout
    assert f"Creating a venv at {sandbox.backend / '.venv'}" in result.stdout
    assert sandbox.calls("setup-python") == [VERSION_CHECK, f"-m venv {sandbox.backend / '.venv'}"]
    # The new venv is filled from the lock, not by pip.
    assert sandbox.calls("uv") == [locked_sync(sandbox)]
    assert [call for call in sandbox.calls("python") if " -m pip " in f" {call} "] == []


def test_setup_creates_no_venv_with_an_old_interpreter(sandbox: Sandbox, tmp_path: Path) -> None:
    # ./dev-start.sh would refuse that venv, and this script never deletes one.
    interpreter = _without_venv_but_an_interpreter(sandbox, tmp_path)

    result = sandbox.run_setup(DEV_SETUP_PYTHON=interpreter, FAKE_SETUP_PYTHON_VERSION_STATUS="1")

    assert result.returncode == 1, result.stdout
    assert "is not Python 3.12 or newer; name one with DEV_SETUP_PYTHON" in result.stdout
    assert sandbox.calls("setup-python") == [VERSION_CHECK]
    assert not (sandbox.backend / ".venv").exists()


@pytest.mark.parametrize("minor", [11, 12])
@pytest.mark.parametrize("action", ["start", "setup"])
def test_developer_preflight_enforces_the_backend_python_floor(sandbox: Sandbox, minor: int, action: str) -> None:
    python = sandbox.backend / ".venv" / "bin" / "python"
    source = python.read_text()
    check = f"import sys; sys.version_info = (3, {minor}, 0); exec(sys.argv[1])"
    prefix = (
        'if [ "$1" = "-c" ]; then\n'
        '  case "$2" in *sys.version_info*)\n'
        f'    exec {shlex.quote(sys.executable)} -c {shlex.quote(check)} "$2" ;;\n'
        '  esac\nfi\n'
    )
    python.write_text(source.replace("#!/bin/sh\n", "#!/bin/sh\n" + prefix, 1))
    sandbox.let_npm_succeed()

    result = sandbox.run_setup() if action == "setup" else sandbox.run()

    if minor == 11:
        assert result.returncode == 1
        assert "does not run Python 3.12 or newer" in result.stdout
        assert sandbox.calls("uv") == [] and sandbox.calls("npm") == []
        assert_nothing_started(sandbox)
    else:
        assert "does not run Python" not in result.stdout
        expected = "Setup done" if action == "setup" else "Database is at Alembic head"
        assert expected in result.stdout
