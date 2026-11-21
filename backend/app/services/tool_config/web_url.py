"""The optional per-connector web URL: where a connector's items open for a person.

Some connectors talk to an API host that is not the host their items open on: Datadog's
``api.datadoghq.com`` vs the account's ``app.datadoghq.eu``, PagerDuty's ``api.pagerduty.com`` vs
``acme.pagerduty.com``, a cloud API vs its console. The platform never guesses that web host. An
administrator sets it explicitly as ``<connector>_web_url`` in the connector config (the tool config
form shows every preset field); the save path validates it here and the admin connector save records
it in the ``admin.connector.saved`` audit like every other config field. Without it, the connector's
items carry no source link (``tests/connector_evidence_coverage_catalog.py``).
"""

from __future__ import annotations

from urllib.parse import urlsplit

WEB_URL_FIELD_SUFFIX = "_web_url"
MAX_WEB_URL_CHARS = 512

# Connector preset -> its web URL field; the field name is the connector's own prefix.
WEB_URL_FIELDS: dict[str, str] = {
    "datadog": "datadog_web_url",
    "newrelic": "newrelic_web_url",
    "snyk": "snyk_web_url",
    "pagerduty": "pagerduty_web_url",
    "statuspage": "statuspage_web_url",
    "aws": "aws_web_url",
    "azure": "azure_web_url",
    "gcp": "gcp_web_url",
}
# The PagerDuty preset also configures Opsgenie (one incident tool set, two providers).
OPSGENIE_WEB_URL_FIELD = "opsgenie_web_url"


def normalize_web_url(value: object) -> str | None:
    """``value`` without a trailing slash when it is an https URL with a host, else ``None``.

    Refused: other schemes, userinfo, whitespace, a query, and values over the bound. A fragment is
    kept (the Azure portal addresses a tenant as ``https://portal.azure.com/#@tenant``).
    """
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or len(raw) > MAX_WEB_URL_CHARS or any(char.isspace() for char in raw):
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc or parts.query:
        return None
    return raw.rstrip("/")


def validate_web_url_field(field_name: str, value: object) -> None:
    """Refuse a configured web URL that is not a valid https base (empty means not configured)."""
    if value in (None, ""):
        return
    if normalize_web_url(value) is None:
        raise ValueError(f"{field_name} must be an https URL with a host, without credentials or a query")


__all__ = [
    "OPSGENIE_WEB_URL_FIELD",
    "WEB_URL_FIELDS",
    "WEB_URL_FIELD_SUFFIX",
    "normalize_web_url",
    "validate_web_url_field",
]
