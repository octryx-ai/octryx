"""The migration check stops the launch on rejected or malformed settings and keeps database credentials off the terminal, files and command lines."""

from __future__ import annotations

import re

import pytest

from tests.db.migrations.dev_launcher_migration_check_support import sandbox  # noqa: F401
from tests.support.dev_launcher_migration_doubles_support import (
    DATABASE_PASSWORD,
    FRAGMENT_SECRET,
    QUERY_SECRET,
    SETTINGS_SECRET,
    requires_alembic,
)
from tests.support.dev_launcher_migration_support import Sandbox, assert_nowhere, assert_stopped_by_the_migration_check
from tests.support.dev_launcher_test_support import free_port, requires_process_tools

pytestmark = [requires_process_tools, requires_alembic]


# (URL after the scheme, how the launcher shows it, SANDBOX_SETTINGS_PRINT); PORT is a free port.
CREDENTIAL_URLS = {
    "password and query": (
        f"launcher:{DATABASE_PASSWORD}@127.0.0.1:PORT/app?password={QUERY_SECRET}",
        "launcher:***@127.0.0.1:PORT/app?…",
        "",
    ),
    # Output printed while the settings load must not shift the raw URL into the shown line.
    "settings that print while loading": (
        f"launcher:{DATABASE_PASSWORD}@127.0.0.1:PORT/app?password={QUERY_SECRET}",
        "launcher:***@127.0.0.1:PORT/app?…",
        "1",
    ),
    "password and fragment": (
        f"launcher:{DATABASE_PASSWORD}@127.0.0.1:PORT/app#{FRAGMENT_SECRET}",
        "launcher:***@127.0.0.1:PORT/app?…",
        "",
    ),
    "IPv6 host, query and fragment": (
        f"launcher:{DATABASE_PASSWORD}@[::1]:PORT/app?sslpassword={QUERY_SECRET}#{FRAGMENT_SECRET}",
        "launcher:***@[::1]:PORT/app?…",
        "",
    ),
    # A generic URL parser ends the password at "?" or "#" and would show the rest.
    "password holding # and ?": (
        f"launcher:{DATABASE_PASSWORD}#{FRAGMENT_SECRET}?{QUERY_SECRET}@127.0.0.1:PORT/app",
        "launcher:***@127.0.0.1:PORT/app",
        "",
    ),
}


def test_rejected_settings_stop_the_launch_without_any_setting_value(sandbox: Sandbox) -> None:  # noqa: F811
    # The raw rejection holds the API key; dev-start.sh must never print that traceback.
    raw = sandbox.python("-c", "from app.config import get_settings; get_settings()", DEBUG="false")
    assert raw.returncode == 1 and SETTINGS_SECRET in raw.stderr

    result = sandbox.run(DEBUG="false")

    reason = "app.config could not resolve the database URL (exit status 1), so no migration ran."
    assert_stopped_by_the_migration_check(sandbox, result, reason)
    # Class, backend frame and pydantic's structured error type; never its message.
    assert "Cause: ValidationError at app/config.py:" in result.stdout
    assert "(in get_settings): settings (value_error)\n" in result.stdout
    assert "insecure defaults" not in result.stdout
    assert "get_settings; get_settings()" in result.stdout
    assert_nowhere(sandbox, result, SETTINGS_SECRET)
    assert "Using database" not in result.stdout
    assert sandbox.alembic_calls() == []
    assert not sandbox.database.exists()


def test_the_settings_boundary_field_reasons_are_shown_and_its_message_is_not(sandbox: Sandbox) -> None:  # noqa: F811
    # app.config raises the boundary's own failure, which offers
    # field/reason pairs as narrow tokens. The gate shows those and still prints no
    # error text, and a pair that is not narrow is filtered like any other value.
    result = sandbox.run(SANDBOX_SAFE_SETTINGS_ERROR="1")

    reason = "app.config could not resolve the database URL (exit status 1), so no migration ran."
    assert_stopped_by_the_migration_check(sandbox, result, reason)
    assert "Cause: SettingsValidationError at app/config.py:" in result.stdout
    assert "(in get_settings): trusted_proxy_ips (malformed_trusted_proxy_allowlist), ? (?)\n" in result.stdout
    assert "settings validation failed" not in result.stdout
    assert_nowhere(sandbox, result, SETTINGS_SECRET)
    assert "Using database" not in result.stdout
    assert sandbox.alembic_calls() == []
    assert not sandbox.database.exists()


def test_empty_database_url_stops_the_launch(sandbox: Sandbox) -> None:  # noqa: F811
    # alembic/env.py would take an empty DATABASE_URL as unset and migrate alembic.ini's database.
    result = sandbox.run(SANDBOX_DATABASE_URL="")

    assert_stopped_by_the_migration_check(sandbox, result, "app.config resolved an empty database URL")
    assert sandbox.alembic_calls() == []
    assert not (sandbox.checkout / "data" / "octryx.db").exists()


@pytest.mark.parametrize(
    "breakage",
    [{"FAKE_PYTHON_NOOP": "-"}, {"SANDBOX_DATABASE_URL": "sqlite+aiosqlite:///first\nsecond"}],
    ids=["no output", "URL spanning lines"],
)
def test_settings_output_other_than_exactly_two_lines_stops_the_launch(
    sandbox: Sandbox, breakage: dict[str, str]  # noqa: F811
) -> None:
    result = sandbox.run(**breakage)

    reason = "app.config printed no well-formed database URL, so no migration ran."
    assert_stopped_by_the_migration_check(sandbox, result, reason)
    assert "Using database" not in result.stdout
    assert sandbox.alembic_calls() == []


@pytest.mark.parametrize("case", list(CREDENTIAL_URLS))
def test_database_credentials_stay_off_the_terminal_files_and_command_lines(sandbox: Sandbox, case: str) -> None:  # noqa: F811
    # Nothing listens on the port, so the upgrade fails after the URL went everywhere it goes.
    port = str(free_port())
    url, shown, settings_print = CREDENTIAL_URLS[case]
    url, shown = url.replace("PORT", port), shown.replace("PORT", port)

    result = sandbox.run(SANDBOX_DATABASE_URL=f"postgresql+asyncpg://{url}", SANDBOX_SETTINGS_PRINT=settings_print)

    assert f"Using database: postgresql+asyncpg://{shown}\n" in result.stdout
    # Whatever the settings step writes besides its two lines is dropped unread.
    assert "settings loaded" not in result.stdout
    assert_stopped_by_the_migration_check(sandbox, result, "'alembic upgrade head' exited with status")
    # The connection failed in env.py, not its import; no revision script was involved.
    assert re.search(r"Cause: [A-Za-z_.]+ at alembic/env\.py:\d+ \(in run_async_migrations\)\n", result.stdout)
    for secret in (DATABASE_PASSWORD, QUERY_SECRET, FRAGMENT_SECRET):
        assert_nowhere(sandbox, result, secret)


def test_database_url_that_does_not_parse_stops_the_launch(sandbox: Sandbox) -> None:  # noqa: F811
    url = f"postgresql+asyncpg://launcher:{DATABASE_PASSWORD}@127.0.0.1:no-port/app"

    result = sandbox.run(SANDBOX_DATABASE_URL=url)

    reason = "app.config could not resolve the database URL (exit status 1), so no migration ran."
    assert_stopped_by_the_migration_check(sandbox, result, reason)
    assert "Cause: ValueError: database_url does not parse as a database URL\n" in result.stdout
    assert_nowhere(sandbox, result, DATABASE_PASSWORD)
    assert sandbox.alembic_calls() == []
