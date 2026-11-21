"""The Source Sync reason of a failed client credentials grant (``services/oidc_client_credentials``).

A grant fails with a closed :class:`OidcTokenError` code; a run records one of the fixed connector reasons
instead, never the identity provider's answer.
"""

from __future__ import annotations

from ....oidc_client_credentials import (
    CODE_INVALID_CLIENT,
    CODE_TOKEN_ENDPOINT_UNREACHABLE,
    CODE_TOKEN_URL_INVALID,
    CODE_UNAUTHORIZED_CLIENT,
    OidcTokenError,
)
from ....servicenow_password_grant import (
    CODE_INVALID_CLIENT as OAUTH_INVALID_CLIENT,
)
from ....servicenow_password_grant import (
    CODE_INVALID_GRANT as OAUTH_INVALID_GRANT,
)
from ....servicenow_password_grant import (
    CODE_UNAUTHORIZED_CLIENT as OAUTH_UNAUTHORIZED_CLIENT,
)
from .contract import (
    REASON_CONNECTION_NOT_CONFIGURED,
    REASON_EGRESS_REFUSED,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_UNAUTHORIZED,
    REASON_SOURCE_UNAVAILABLE,
)

_OAUTH_REFUSALS = (OAUTH_INVALID_CLIENT, OAUTH_INVALID_GRANT, OAUTH_UNAUTHORIZED_CLIENT)  # also password grant


def reason_for_token_error(error: OidcTokenError) -> str:
    """The fixed reason: a refused client (any 4xx of the token endpoint) is ``source_unauthorized``."""
    if error.egress_refused:
        return REASON_EGRESS_REFUSED
    if error.code in (CODE_INVALID_CLIENT, CODE_UNAUTHORIZED_CLIENT, *_OAUTH_REFUSALS):
        return REASON_SOURCE_UNAUTHORIZED
    if error.code == CODE_TOKEN_ENDPOINT_UNREACHABLE:
        return REASON_SOURCE_UNAVAILABLE
    if error.code == CODE_TOKEN_URL_INVALID:
        return REASON_CONNECTION_NOT_CONFIGURED
    if error.http_status is not None and 400 <= error.http_status < 500:
        return REASON_SOURCE_UNAUTHORIZED
    return REASON_SOURCE_CONTRACT_VIOLATION  # a redirect or no usable token


__all__ = ["reason_for_token_error"]
