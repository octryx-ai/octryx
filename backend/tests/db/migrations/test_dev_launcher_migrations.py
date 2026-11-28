"""The Alembic migration check of the local dev launcher: check_migrations in dev-start.sh."""

from __future__ import annotations

import shutil
from collections.abc import Callable

import pytest

from tests.db.migrations.dev_launcher_migration_check_support import sandbox  # noqa: F401
from tests.support.dev_launcher_migration_doubles_support import (
    SETTINGS_SECRET,
    TOKEN_SECRET,
    requires_alembic,
    revision,
)
from tests.support.dev_launcher_migration_support import (
    Sandbox,
    assert_nowhere,
    assert_stopped_by_the_migration_check,
    assert_went_on_to_the_frontend_build,
)
from tests.support.dev_launcher_test_support import requires_process_tools

pytestmark = [requires_process_tools, requires_alembic]


MIGRATION_METADATA_IMPORT = "from app.db.migration_metadata import load_migration_metadata"


def _take_metadata_from_migration_metadata(sandbox: Sandbox) -> None:  # noqa: F811
    env_py = sandbox.backend / "alembic" / "env.py"
    source = env_py.read_text(encoding="utf-8")
    if MIGRATION_METADATA_IMPORT not in source:
        lines = source.splitlines(keepends=True)
        source = "".join(
            line for line in lines if not line.startswith(("from app.db import", "from app.models import"))
        )
        source = source.replace(
            "from alembic import context\n", f"from alembic import context\n{MIGRATION_METADATA_IMPORT}\n"
        )
        source = source.replace("target_metadata = Base.metadata", "target_metadata = load_migration_metadata()")
    assert MIGRATION_METADATA_IMPORT in source and "target_metadata = load_migration_metadata()" in source
    assert "from app.models import" not in source
    env_py.write_text(source, encoding="utf-8")


def _remove_versions(sandbox: Sandbox) -> str:  # noqa: F811
    shutil.rmtree(sandbox.versions)
    return f"'alembic heads' listed no revision because {sandbox.versions} is missing."


def _point_version_locations_elsewhere(sandbox: Sandbox) -> str:  # noqa: F811
    ini = sandbox.backend / "alembic.ini"
    source = ini.read_text(encoding="utf-8")
    assert source.startswith("[alembic]\n")
    ini.write_text(source.replace("[alembic]\n", "[alembic]\nversion_locations = %(here)s/nowhere\n", 1))
    return (
        f"'alembic heads' listed no revision although {sandbox.versions} holds revision scripts; "
        "check version_locations in backend/alembic.ini."
    )


def test_fresh_database_is_migrated_before_the_launch_goes_on(sandbox: Sandbox) -> None:  # noqa: F811
    result = sandbox.run()

    assert f"Using database: {sandbox.url}" in result.stdout
    assert "Database is at Alembic head r2" in result.stdout
    assert sandbox.upgrades() == ["r1", "r2"]
    assert sandbox.revisions_in_database() == ["r2"]
    # The URL reached Alembic explicitly: alembic.ini's fallback database was never created.
    assert not (sandbox.checkout / "data" / "octryx.db").exists()
    assert_nowhere(sandbox, result, SETTINGS_SECRET)
    assert_went_on_to_the_frontend_build(sandbox, result)


@pytest.mark.parametrize("printed", [f"{TOKEN_SECRET} loaded", TOKEN_SECRET], ids=["words", "a bare token"])
def test_output_a_revision_prints_while_loading_is_never_shown(sandbox: Sandbox, printed: str) -> None:  # noqa: F811
    # It reaches the standard output of `heads` and `current`, where only listing lines are
    # revisions. A bare token looks like a current revision that is no head: the comparison then
    # fails closed, and the current revisions are never shown.
    sandbox.write_revision("r2_second", revision("r2", "r1", header=f'print("{printed}")\n'))

    result = sandbox.run()

    if printed == TOKEN_SECRET:
        assert_stopped_by_the_migration_check(sandbox, result, "The database is not at the Alembic head 'r2'")
    else:
        assert "Database is at Alembic head r2" in result.stdout
        assert_went_on_to_the_frontend_build(sandbox, result)
    assert_nowhere(sandbox, result, TOKEN_SECRET)


def test_database_is_shown_literally(sandbox: Sandbox) -> None:  # noqa: F811
    # echo -e would read "\c" in the path as "stop printing here" and drop the rest of the line.
    database = sandbox.checkout / "data" / "app-a\\cb.db"
    url = f"sqlite+aiosqlite:///{database}"

    result = sandbox.run(SANDBOX_DATABASE_URL=url)

    assert f"Using database: {url}\n" in result.stdout
    assert "Database is at Alembic head r2" in result.stdout
    assert_went_on_to_the_frontend_build(sandbox, result)


def test_env_py_taking_its_metadata_from_migration_metadata_migrates(sandbox: Sandbox) -> None:  # noqa: F811
    # The env.py imports the models behind app.db.migration_metadata; the sandbox must follow.
    _take_metadata_from_migration_metadata(sandbox)
    record = sandbox.checkout / "data" / "metadata-loads"

    result = sandbox.run(SANDBOX_METADATA_RECORD=str(record))

    assert "Database is at Alembic head r2" in result.stdout
    # Loaded by env.py for the upgrade and again for the check of the current revision.
    assert record.read_text(encoding="utf-8").splitlines() == ["loaded", "loaded"]
    assert sandbox.revisions_in_database() == ["r2"]
    assert_went_on_to_the_frontend_build(sandbox, result)


def test_env_py_taking_its_metadata_from_migration_metadata_names_the_model_frame(sandbox: Sandbox) -> None:  # noqa: F811
    _take_metadata_from_migration_metadata(sandbox)

    result = sandbox.run(SANDBOX_LIBRARY_FAILS="1")

    reason = "'alembic upgrade head' exited with status 1; the database is not at the Alembic head."
    assert_stopped_by_the_migration_check(sandbox, result, reason)
    assert "Cause: RuntimeError at app/models/__init__.py:" in result.stdout


def test_current_database_goes_on_without_migrating_again(sandbox: Sandbox) -> None:  # noqa: F811
    sandbox.alembic("upgrade", "head")
    assert sandbox.upgrades() == ["r1", "r2"]

    result = sandbox.run()

    assert "Database is at Alembic head r2" in result.stdout
    assert sandbox.upgrades() == ["r1", "r2"]
    assert sandbox.revisions_in_database() == ["r2"]
    assert_went_on_to_the_frontend_build(sandbox, result)


def test_genuinely_empty_revision_graph_skips_the_migrations(sandbox: Sandbox) -> None:  # noqa: F811
    for script in sandbox.versions.glob("*.py"):
        script.unlink()
    (sandbox.versions / "__init__.py").write_text("", encoding="utf-8")

    result = sandbox.run()

    assert f"No Alembic revisions in {sandbox.versions} — skipping migrations." in result.stdout
    assert sandbox.alembic_calls() == ["-m alembic heads"]
    assert_went_on_to_the_frontend_build(sandbox, result)


@pytest.mark.parametrize(
    "breakage",
    [_remove_versions, _point_version_locations_elsewhere],
    ids=["missing versions directory", "misdirected version_locations"],
)
def test_graph_that_only_looks_empty_stops_the_launch(sandbox: Sandbox, breakage: Callable[[Sandbox], str]) -> None:  # noqa: F811
    # Alembic lists no revision for both, exactly as for a genuinely empty graph.
    reason = breakage(sandbox)

    result = sandbox.run()

    assert_stopped_by_the_migration_check(sandbox, result, reason)
    assert sandbox.alembic_calls() == ["-m alembic heads"]
