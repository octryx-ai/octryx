"""A refused Jira ``releases`` block names its field and a fixed code, never the value; the path indexes
follow the order the connectors editor sends."""

from __future__ import annotations

import json

import pytest

from app.api.routes.knowledge._knowledge_connector_http import release_config_refusal
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.jira_release_config import InvalidReleaseConfigError

VALID = {
    "products": {"OPS": "Acme-Orders"},
    "version_name_prefixes": ["Release "],
    "sections": [{"title": "Features", "issue_types": ["Story"], "labels": []}],
    "blocker_priorities": ["Blocker"],
}


def _configure(releases: object):
    return validate_config(connector_key="ops", kind="jira", project_keys=["OPS", "PLAT"], releases=releases)


def test_a_valid_block_is_stored_normalized() -> None:
    scope = _configure(VALID).scope
    assert scope["releases"]["products"] == {"OPS": "acme-orders"}
    assert scope["releases"]["version_name_prefixes"] == ["Release "]


@pytest.mark.parametrize(
    ("releases", "field", "code"),
    [
        ({"products": {"OPS": "ok", "ZZZ": "x"}}, "releases.products[1]", "release_project_not_in_scope"),
        ({"products": {"ops": "x"}}, "releases.products[0]", "release_project_key_invalid"),
        ({"products": {"OPS": "Acme Orders!"}}, "releases.products[0]", "release_product_invalid"),
        ({"version_name_prefixes": ["x" * 41]}, "releases.version_name_prefixes[0]", "release_value_too_long"),
        (
            {"version_name_prefixes": ["a", "b", "c", "d", "e", "f"]},
            "releases.version_name_prefixes",
            "release_too_many_values",
        ),
        ({"blocker_priorities": ["  "]}, "releases.blocker_priorities[0]", "release_value_invalid"),
        (
            {"sections": [VALID["sections"][0], {"title": "Bugs"}]},
            "releases.sections[1]",
            "release_section_without_match",
        ),
        ({"sections": [{"title": "", "labels": ["x"]}]}, "releases.sections[0].title", "release_section_title_invalid"),
        ({"surprise": 1}, "releases", "release_block_invalid"),
    ],
)
def test_a_refusal_names_the_field_and_a_fixed_code(releases: object, field: str, code: str) -> None:
    with pytest.raises(InvalidReleaseConfigError) as caught:
        _configure(releases)
    assert (caught.value.field, caught.value.code) == (field, code)
    refusal = release_config_refusal(caught.value)
    assert refusal.status_code == 400
    assert refusal.detail == {"state": "invalid_request", "reason": code, "field": field}
    # Never the refused value itself.
    assert "Acme Orders" not in json.dumps(refusal.detail) and "xxxx" not in json.dumps(refusal.detail)
