"""The origin link of a source revision, e.g. a Confluence page or a specification PDF.

Evidence must say where it came from in a form a person can open. Each immutable
revision may carry the URL of exactly the version it captured; citations carry it to
the chat and the UI as a link. The value is untrusted input, so it is accepted only as
an absolute ``http``/``https`` URL with a host, without credentials, whitespace or
control characters, and within a bounded length. Nothing is fetched, resolved or
guessed: a revision without a URL is shown as having no link.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from ..ledger.errors import InvalidEvidenceRequestError

MAX_SOURCE_URL_CHARS = 2048


def normalize_source_url(raw: object) -> str | None:
    """Return a safe, openable URL, ``None`` for no URL, or refuse the request."""
    if raw is None:
        return None
    if type(raw) is not str:
        raise InvalidEvidenceRequestError()
    value = raw.strip()
    if not value:
        return None
    if len(value) > MAX_SOURCE_URL_CHARS or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise InvalidEvidenceRequestError()
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise InvalidEvidenceRequestError()
    if parts.username is not None or parts.password is not None:
        raise InvalidEvidenceRequestError()
    try:
        parts.port  # noqa: B018 - validates the port range
    except ValueError:
        raise InvalidEvidenceRequestError() from None
    return parts._replace(scheme=parts.scheme.lower()).geturl()


def page_link(source_url: str | None, media_type: str | None, page: int | None) -> str | None:
    """The origin link opened at a page, for a PDF revision whose span knows its page.

    ``#page=N`` is the open PDF fragment every mainstream viewer honours. A URL that already
    carries a fragment is left untouched rather than rewritten.
    """
    if source_url is None or media_type != "application/pdf" or type(page) is not int or page < 1:
        return source_url
    if "#" in source_url:
        return source_url
    return f"{source_url}#page={page}"


def line_link(source_url: str | None, line_start: int | None, line_end: int | None) -> str | None:
    """The origin link opened at a line range, for a code span: ``#L<start>-L<end>``.

    GitHub's blob view and the platform's source viewer both honour it; one line is ``#L<n>``. A URL
    that already carries a fragment is left untouched rather than rewritten.
    """
    if source_url is None or type(line_start) is not int or line_start < 1 or "#" in source_url:
        return source_url
    if type(line_end) is not int or line_end <= line_start:
        return f"{source_url}#L{line_start}"
    return f"{source_url}#L{line_start}-L{line_end}"


__all__ = ["MAX_SOURCE_URL_CHARS", "line_link", "normalize_source_url", "page_link"]
