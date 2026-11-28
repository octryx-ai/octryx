from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args

from app.services.knowledge.access.acl_keys import (
    PUBLIC_ACL_KEY,
    RESTRICTED_ACL_KEY,
    AclKey,
    MarkerKey,
    is_principal_key,
    principal_key_for_email,
    query_acl_keys,
    reader_principal_keys,
    span_acl_keys,
)
from app.services.knowledge.sources.repository_snapshot.binding import LINKS_HOST, LINKS_PLATFORM
from app.services.knowledge.sources.repository_snapshot.protocol_types import LinkMode
from app.services.knowledge.sources.sync.cursor import SyncCursor
from app.services.knowledge.sources.sync.incremental import MODE_FULL, MODE_INCREMENTAL, MODE_INCREMENTAL_FALLBACK
from app.services.knowledge.sources.sync.jira_release_config import validate_release_config
from app.services.knowledge.sources.sync.rest_config import MEDIA_TYPES, VISIBILITY_RESTRICTED, VISIBILITY_WORKSPACE
from app.services.knowledge.sources.sync.run_report import COUNT_KEYS
from app.services.knowledge.sources.sync.stored_types import (
    RestMediaType,
    RestVisibility,
    StoredReleaseConfig,
    StoredSyncCursor,
    SyncMode,
    SyncOutcome,
)
from tests.typed_dict_support import shape_problems

NOW = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)


class _Reader:
    is_active = True
    account_type = "human"
    email = "Reader@Example.test"


def test_every_cursor_transition_stores_a_stored_sync_cursor():
    started = SyncCursor().begin_pass(NOW, scheduled=True).at("0:/rest/api/content?cursor=x").with_failures(1)
    incremental = started.complete_pass(NOW).begin_incremental(NOW).at_incremental("2:40")
    cursors = [SyncCursor(), started, started.complete_pass(NOW), incremental, incremental.complete_incremental(),
               SyncCursor().begin_pass(NOW).complete_pass(NOW)]
    for cursor in cursors:
        stored = cursor.as_dict()
        assert shape_problems(stored, StoredSyncCursor, "cursor") == []
        assert SyncCursor.load(stored) == cursor


def test_a_validated_release_block_is_a_stored_release_config():
    raw = {"products": {"OPS": "orders"}, "version_name_prefixes": ["Release "], "blocker_priorities": ["Blocker"],
           "sections": [{"title": "Fixes", "issue_types": ["Bug"]}, {"title": "Security", "labels": ["cve"]}]}
    for block in (raw, {"products": {}}):
        stored = validate_release_config(block, project_keys=("OPS",))
        assert shape_problems(stored, StoredReleaseConfig, "releases") == []


def test_the_literal_vocabularies_are_the_constants_the_code_compares_with():
    assert get_args(RestMediaType) == MEDIA_TYPES
    assert set(get_args(RestVisibility)) == {VISIBILITY_RESTRICTED, VISIBILITY_WORKSPACE}
    assert get_args(SyncOutcome) == COUNT_KEYS
    assert set(get_args(SyncMode)) == {MODE_FULL, MODE_INCREMENTAL, MODE_INCREMENTAL_FALLBACK}
    assert set(get_args(LinkMode)) == {LINKS_HOST, LINKS_PLATFORM}
    assert set(get_args(MarkerKey)) == {PUBLIC_ACL_KEY, RESTRICTED_ACL_KEY}


def test_produced_acl_keys_are_markers_or_principal_keys():
    principal = principal_key_for_email(" Reader@Example.test ")
    assert is_principal_key(principal) and reader_principal_keys(_Reader()) == (principal,)
    produced = [query_acl_keys((principal,)), span_acl_keys((principal,)), span_acl_keys(None), query_acl_keys(())]
    for keys in produced:
        assert shape_problems(keys, tuple[AclKey, ...], "keys") == []
        assert all(key in get_args(MarkerKey) or is_principal_key(key) for key in keys)
