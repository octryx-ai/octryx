from __future__ import annotations

import pytest

from app.services.data_access.reviewed_sql import CONNECTION_READ_MODULES, TABLE_CLAUSE_MODULES, TEXT_SQL_MODULES
from tests.guards._data_viewer_allowlist import MAINTENANCE_SITES, SESSION_SITES
from tests.guards._session_viewers import (
    connection_read_modules,
    maintenance_sites,
    table_clause_modules,
    text_sql_modules,
    undeclared_session_sites,
)
from tests.guards._support import assert_guard
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")




def test_platform_maintenance_runs_only_at_the_pinned_sites_with_their_reasons():
    assert_guard(maintenance_sites(), MAINTENANCE_SITES, what="platform_maintenance site")


def test_text_sql_runs_only_in_reviewed_modules():
    assert text_sql_modules() == TEXT_SQL_MODULES.keys()


def test_reads_through_a_connection_run_only_in_reviewed_modules():
    assert connection_read_modules() == CONNECTION_READ_MODULES.keys()


def test_lightweight_table_clauses_run_only_in_reviewed_modules():
    assert table_clause_modules() == TABLE_CLAUSE_MODULES.keys()


def test_every_session_opened_outside_a_viewer_block_names_where_its_viewer_comes_from():
    sites = undeclared_session_sites()
    assert sorted(sites - SESSION_SITES.keys()) == [], "new: wrap it in as_viewer/platform_maintenance or pin it"
    assert sorted(SESSION_SITES.keys() - sites) == [], "stale entries"
