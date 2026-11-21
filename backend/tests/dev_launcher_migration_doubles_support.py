"""Test doubles and canary secrets of the dev launcher migration sandbox (``dev_launcher_migration_support``).

The tools the launcher runs, the minimal ``app`` package env.py imports, the revision builder and the
payloads of a failing revision. Every canary secret planted in a sandbox is defined here.
"""

from __future__ import annotations

import importlib.util

import pytest

from tests.dev_launcher_test_support import REPO_ROOT

MIGRATION_GATE = REPO_ROOT / "scripts" / "dev-migration-gate.sh"

requires_alembic = pytest.mark.skipif(
    any(importlib.util.find_spec(name) is None for name in ("alembic", "aiosqlite", "pydantic")),
    reason="the migration check runs Alembic on SQLite through aiosqlite, with pydantic settings",
)

# Short enough to survive pydantic's truncation of the input it echoes into a validation error.
SETTINGS_SECRET = "sk-ca" + "nary-7d41"
REVISION_SECRET = "sk-canary-9c3e"
STAMP_SECRET = "sk-canary-2e6a"
DATABASE_PASSWORD = "sk-ca" + "nary-5b80"
QUERY_SECRET = "sk-ca" + "nary-31fd"
FRAGMENT_SECRET = "sk-canary-c07e"
# Shaped like an identifier, so a parser that reads names from output could take it for one.
TOKEN_SECRET = "ghp_ca" + "nary_7d41"

FAKE_PYTHON = r"""#!/bin/sh
printf '%s\n' "$*" >>"CALLS/python"
case " $* " in
  *" -m pip "*) exit 0 ;;
  *" -m uvicorn "*) echo "launcher test: refusing to start a server" >&2; exit 97 ;;
esac
if [ "$1" = "-" ] && [ "$#" -gt 1 ]; then
  echo "launcher test: refusing to launch a detached process" >&2
  exit 97
fi
if [ -n "${FAKE_PYTHON_FAIL:-}" ] && [ "$*" = "$FAKE_PYTHON_FAIL" ]; then
  echo "launcher test: simulated failure" >&2
  exit 3
fi
if [ -n "${FAKE_PYTHON_NOOP:-}" ] && [ "$*" = "$FAKE_PYTHON_NOOP" ]; then
  exit 0
fi
exec "REAL_PYTHON" "$@"
"""

RECORDING_TOOL = r"""#!/bin/sh
printf '%s\n' "$*" >>"CALLS/NAME"
exit STATUS
"""

#: The uv pin dev-setup.sh accepts from PATH (its DEV_SETUP_UV_VERSION default).
PINNED_UV_VERSION = "0.12.19"

FAKE_UV = r"""#!/bin/sh
if [ "$*" = "--version" ]; then
  echo "uv PINNED_UV_VERSION"
  exit 0
fi
printf '%s\n' "$*" >>"CALLS/uv"
exit "${FAKE_UV_STATUS:-0}"
""".replace("PINNED_UV_VERSION", PINNED_UV_VERSION)

# The URL comes from SANDBOX_DATABASE_URL, never from DATABASE_URL, like a URL that only the
# checkout's .env holds: Alembic sees the right database only if the launcher passes it on. A
# rejection carries the API key twice, as pydantic's echoed input and quoted by the validator.
SETTINGS_MODULE = """import os

from pydantic import BaseModel, model_validator


class SettingsValidationError(RuntimeError):
    \"\"\"Stands in for app.settings_validation_policy's failure.

    Narrow field/reason tokens next to a message the gate must not print, plus a
    pair that is not narrow at all, so the gate's filter is what decides.
    \"\"\"

    def __init__(self):
        super().__init__("settings validation failed, openrouter_api_key=SETTINGS_SECRET")
        self.safe_field_reasons = (
            ("trusted_proxy_ips", "malformed_trusted_proxy_allowlist"),
            ("openrouter_api_key=SETTINGS_SECRET", "reason SETTINGS_SECRET"),
        )


class Settings(BaseModel):
    debug: bool = True
    database_url: str = ""
    openrouter_api_key: str = ""

    @model_validator(mode="after")
    def reject_insecure_defaults(self):
        if not self.debug:
            raise ValueError(f"insecure defaults, openrouter_api_key={self.openrouter_api_key}")
        return self


def get_settings():
    if os.environ.get("SANDBOX_SETTINGS_PRINT"):
        print("settings loaded")
    if os.environ.get("SANDBOX_SAFE_SETTINGS_ERROR"):
        raise SettingsValidationError()
    return Settings(
        debug=os.environ.get("DEBUG") != "false",
        database_url=os.environ.get("SANDBOX_DATABASE_URL", ""),
        openrouter_api_key="SETTINGS_SECRET",
    )
""".replace("SETTINGS_SECRET", SETTINGS_SECRET)

# env.py imports every model. With SANDBOX_LIBRARY_FAILS, a model import fails inside a library
# of the venv below this backend, whose frames the launcher must not name.
MODELS_MODULE = """import os
import sys

if os.environ.get("SANDBOX_LIBRARY_FAILS"):
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "../../.venv/lib")))
    import launcher_test_library  # noqa: F401
"""

# Since the parity revisions, env.py takes its target metadata from app.db.migration_metadata, which imports
# the models itself. With SANDBOX_METADATA_RECORD set, each call leaves a line in that file.
MIGRATION_METADATA_MODULE = """import os

from app.db import Base


def load_migration_metadata():
    from app import models  # noqa: F401

    record = os.environ.get("SANDBOX_METADATA_RECORD")
    if record:
        with open(record, "a") as handle:
            handle.write("loaded\\n")
    return Base.metadata
"""

APP_PACKAGE = {
    "__init__.py": "",
    "db/__init__.py": "from sqlalchemy.orm import declarative_base\n\nBase = declarative_base()\n",
    "db/migration_metadata.py": MIGRATION_METADATA_MODULE,
    "models/__init__.py": MODELS_MODULE,
    "config.py": SETTINGS_MODULE,
}
VENV_LIBRARY = 'raise RuntimeError("launcher test library failure")\n'


def revision(rev: str, down: str | None, *, fails: bool = False, header: str = "", body: str = "") -> str:
    """A revision that creates table_<rev> and appends its ID to $SANDBOX_UPGRADE_RECORD.

    ``header`` runs when the module is imported, ``body`` at the end of upgrade().
    """
    # A failing data step, whose message carries a value from the database.
    failure = body + (f'    raise RuntimeError("revision {rev} failed on {REVISION_SECRET}")\n' if fails else "")
    return (
        f'"""Revision {rev}."""\n'
        "import os\n\nimport sqlalchemy as sa\n\nfrom alembic import op\n"
        f"{header}\n"
        f"revision = {rev!r}\ndown_revision = {down!r}\nbranch_labels = None\ndepends_on = None\n\n\n"
        "def upgrade():\n"
        f"    op.create_table('table_{rev}', sa.Column('id', sa.Integer, primary_key=True))\n"
        "    with open(os.environ['SANDBOX_UPGRADE_RECORD'], 'a') as record:\n"
        f"        record.write('{rev}\\n')\n"
        f"{failure}\n\n"
        f"def downgrade():\n    op.drop_table('table_{rev}')\n"
    )


# Payloads for a failing r3. Only the first line of an exception is read: the second line of these
# messages is shaped like an exception class and carries the secret. The first line of the
# non-ASCII class is no plain class name (like a colored traceback), so no line of it is read.
LOCAL_EXCEPTION = f'    class DataError(Exception):\n        pass\n\n    raise DataError("row\\n{TOKEN_SECRET}")\n'
NON_ASCII_EXCEPTION = f'    class Fehlerä(Exception):\n        pass\n\n    raise Fehlerä("x\\n{TOKEN_SECRET}")\n'
INVALID_UTF8 = f'    os.write(2, b"\\xff\\xfe {TOKEN_SECRET}\\n")\n'
FAILED_DECOY = f'print("FAILED: decoy {TOKEN_SECRET}")\n'
