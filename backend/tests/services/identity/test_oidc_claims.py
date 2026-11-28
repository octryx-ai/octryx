from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import IdentityProvider
from app.services.oidc_claims import (
    default_group_ids,
    default_role_names,
    group_group_mappings,
    group_role_mappings,
    resolve_identity_claims,
)


def test_resolve_identity_claims_uses_custom_nested_mappings() -> None:
    provider = IdentityProvider(
        claim_mappings_json={
            "subject": "user.sub",
            "email": "user.contact.email",
            "username": "user.profile.username",
            "display_name": "user.profile.name",
            "groups": "user.membership.groups",
        }
    )

    resolved = resolve_identity_claims(
        provider,
        {
            "user": {
                "sub": "subject-123",
                "contact": {"email": "person@example.com"},
                "profile": {"username": "person", "name": "Person Example"},
                "membership": {"groups": ["admins", "", "operators"]},
            }
        },
    )

    assert resolved.subject == "subject-123"
    assert resolved.external_email == "person@example.com"
    assert resolved.external_username == "person"
    assert resolved.display_name == "Person Example"
    assert resolved.external_groups == ["admins", "operators"]


def test_resolve_identity_claims_requires_subject() -> None:
    provider = IdentityProvider()

    with pytest.raises(HTTPException) as exc_info:
        resolve_identity_claims(provider, {"email": "person@example.com"})

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "OIDC claims missing subject"


def test_group_role_mappings_discards_blank_entries() -> None:
    provider = IdentityProvider(
        group_role_mappings_json={
            " admins ": ["admin", " ", "operator"],
            "reviewers": "viewer",
            "": ["ignored"],
            "empty": " ",
        }
    )

    assert group_role_mappings(provider) == {
        "admins": ["admin", "operator"],
        "reviewers": ["viewer"],
    }


def test_group_group_and_default_mappings_discard_blank_entries() -> None:
    provider = IdentityProvider(
        group_group_mappings_json={
            " admins ": ["group-a", " ", "group-b"],
            "reviewers": "group-c",
            "": ["ignored"],
        },
        default_roles_json=["viewer", "", "operator"],
        default_group_ids_json=["group-a", " ", "group-d"],
    )

    assert group_group_mappings(provider) == {
        "admins": ["group-a", "group-b"],
        "reviewers": ["group-c"],
    }
    assert default_role_names(provider) == ["viewer", "operator"]
    assert default_group_ids(provider) == ["group-a", "group-d"]
