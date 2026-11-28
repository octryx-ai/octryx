"""AWS: one named connection per account (role or keys), bound to account ids."""

from __future__ import annotations

from ..descriptor import (
    CASE_EXACT,
    UNSCOPED_SINGLE,
    Binding,
    ConnectorDescriptor,
    Field,
    UnitIncompleteError,
    present,
)

PLATFORM_CREDENTIALS = "allow_platform_credentials"


def _account_keys(tool_name: str, params: dict) -> tuple[str, ...]:
    account = params.get("account_id")
    return (str(account).strip(),) if isinstance(account, str | int) and str(account).strip() else ()


def _check(config: dict, *, has) -> None:
    if not has(config, "aws_region"):
        raise UnitIncompleteError("connection_invalid", "An own AWS connection needs aws_region.")
    key_id, secret = has(config, "aws_access_key_id"), has(config, "aws_secret_access_key")
    if key_id != secret:
        raise UnitIncompleteError("connection_invalid",
                                  "aws_access_key_id and aws_secret_access_key belong together.")
    if not (key_id or has(config, "aws_role_arn") or config.get(PLATFORM_CREDENTIALS) is True):
        raise UnitIncompleteError(
            "connection_invalid",
            "An own AWS connection needs a key pair, an aws_role_arn or allow_platform_credentials.",
        )


def _complete(config: dict) -> None:
    _check(config, has=present)


def _resolved(config: dict, name: str) -> bool:
    return bool(str(config.get(name) or "").strip())


def _runtime_guard(config: dict) -> None:
    try:
        _check(config, has=_resolved)
    except UnitIncompleteError:
        raise UnitIncompleteError(
            "named_connection_credential_unavailable",
            "its keys or role are not available (no fallback to the host's credentials).",
        ) from None


AWS = ConnectorDescriptor(
    connector="aws",
    label="AWS",
    binding=Binding("account", "Accounts", r"[0-9]{12}", CASE_EXACT, "123456789012, 210987654321"),
    fields=(
        Field("aws_region", "Region", required=True, placeholder="region"),
        Field("aws_role_arn", "Role ARN", placeholder="arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME"),
        Field(PLATFORM_CREDENTIALS, "Allow the platform's own credentials (no keys, no role)", kind="bool"),
        Field("aws_access_key_id", "Access key id", kind="secret"),
        Field("aws_secret_access_key", "Secret access key", kind="secret"),
        Field("aws_session_token", "Session token", kind="secret"),
    ),
    usable_field="aws_region",
    default_usable_fields=("aws_role_arn", "aws_access_key_id", "aws_access_key_id_secret_ref", "aws_profile",
                           PLATFORM_CREDENTIALS),
    request_keys=_account_keys,
    request_params={"account_id": {
        "type": "string",
        "description": "Optional: the 12-digit AWS account to query; the call runs on the connection bound to it.",
    }},
    default_key_fields=("aws_account_id",),
    unscoped=UNSCOPED_SINGLE,
    named_drops=("aws_profile",),
    complete=_complete,
    runtime_guard=_runtime_guard,
)

__all__ = ["AWS"]
