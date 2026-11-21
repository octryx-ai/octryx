import pytest

from app.services import secret as secret_service


def test_encrypt_secret_uses_fernet_prefix_and_roundtrips():
    encrypted = secret_service.encrypt_secret("super-secret")

    assert encrypted.startswith("fernet:")
    assert secret_service.decrypt_secret(encrypted) == "super-secret"


def test_decrypt_secret_refuses_a_value_without_the_fernet_prefix():
    with pytest.raises(ValueError, match="Unknown secret format"):
        secret_service.decrypt_secret("bm90LWEtZmVybmV0LXRva2Vu")


def test_secret_reference_contract_defines_public_and_persisted_ref_shapes():
    contract = secret_service.secret_reference_contract()

    assert contract["public_label_prefix"] == "secret:"
    assert contract["config_ref_suffix"] == "_secret_ref"
    assert contract["persisted_value"] == "stored_secret_id"
    assert contract["resolution_scope"] == "tool_name + field_name + project_id"
    assert secret_service.secret_ref_label("abc") == "secret:abc"
    assert secret_service.normalize_secret_ref("secret:abc") == "abc"
    assert secret_service.normalize_secret_ref("abc") == "abc"
    assert secret_service.secret_ref_field_name("jira_token") == "jira_token_secret_ref"
    assert secret_service.secret_value_field_name("jira_token_secret_ref") == "jira_token"


@pytest.mark.asyncio
async def test_resolve_secret_refs_requires_matching_tool_field_scope(db):
    correct = await secret_service.set_secret_value(
        db,
        tool_name="jira",
        field_name="jira_token",
        project_id=None,
        value="jira-secret",
    )
    wrong_scope = await secret_service.set_secret_value(
        db,
        tool_name="github",
        field_name="github_token",
        project_id=None,
        value="github-secret",
    )
    await db.commit()

    resolved = await secret_service.resolve_secret_refs(
        db,
        {"jira_token_secret_ref": f"secret:{wrong_scope.id}"},
        tool_name="jira",
        project_id=None,
    )

    assert "jira_token" not in resolved

    resolved = await secret_service.resolve_secret_refs(
        db,
        {"jira_token_secret_ref": f"secret:{correct.id}"},
        tool_name="jira",
        project_id=None,
    )

    assert resolved["jira_token"] == "jira-secret"
