"""Jenkins: one named connection per CI server, bound to instance labels."""

from __future__ import annotations

from ..descriptor import UNSCOPED_SINGLE, ConnectorDescriptor, Field, UnitIncompleteError, require_fields
from .observability import INSTANCE_BINDING, INSTANCE_PARAM, _instance_keys

_REQUIRED = ("jenkins_url", "jenkins_username", "jenkins_token")


def _complete(config: dict) -> None:
    require_fields(config, *_REQUIRED)


def _guard(config: dict) -> None:
    if not all(str(config.get(name) or "").strip() for name in _REQUIRED):
        raise UnitIncompleteError("named_connection_credential_unavailable", "its URL, user or token is not available.")


JENKINS = ConnectorDescriptor(
    connector="jenkins",
    label="Jenkins",
    binding=INSTANCE_BINDING,
    fields=(
        Field("jenkins_url", "Jenkins URL", kind="url", required=True),
        Field("jenkins_username", "User", required=True),
        Field("jenkins_token", "API token", kind="secret", required=True),
    ),
    usable_field="jenkins_url",
    request_keys=_instance_keys,
    request_params=INSTANCE_PARAM,
    unscoped=UNSCOPED_SINGLE,
    complete=_complete,
    runtime_guard=_guard,
    testable=False,
)

__all__ = ["JENKINS"]
