"""The optional per-connector web URL: where a connector's items open for a person."""

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
