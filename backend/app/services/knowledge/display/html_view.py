"""Strict allowlist rendering of an untrusted HTML original for display (stdlib only). Nothing from the input is copied
through as markup."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

from ..text_safety import remove_unsafe_chars

ALLOWED_TAGS = frozenset({
    "a", "abbr", "b", "blockquote", "br", "caption", "cite", "code", "col", "colgroup", "dd", "del", "div",
    "dl", "dt", "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "ins", "kbd",
    "li", "mark", "ol", "p", "pre", "q", "s", "samp", "small", "span", "strong", "sub", "sup", "table",
    "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
})
ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title"}),
    "abbr": frozenset({"title"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan", "scope"}),
    "ol": frozenset({"start"}),
    "col": frozenset({"span"}),
    "colgroup": frozenset({"span"}),
}
# Dropped with everything inside them.
DROPPED_WITH_CONTENT = frozenset({
    "applet", "audio", "base", "button", "canvas", "embed", "form", "frame", "frameset", "head", "iframe",
    "input", "link", "math", "meta", "noembed", "noframes", "noscript", "object", "option", "script",
    "select", "style", "svg", "template", "textarea", "title", "video",
})
VOID_TAGS = frozenset({"br", "hr", "col", "img", "input", "meta", "link", "base", "embed", "source", "wbr"})
BLOCK_TAGS = frozenset({
    "blockquote", "br", "caption", "dd", "div", "dl", "dt", "figcaption", "figure", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "li", "ol", "p", "pre", "section", "article", "header", "footer", "table", "tr", "ul",
})
LINK_SCHEMES = frozenset({"http", "https", "mailto"})
MAX_DEPTH = 100
MAX_ATTRIBUTE_CHARS = 2048

_NUMBER = re.compile(r"^[0-9]{1,4}$")
_SCOPES = frozenset({"row", "col", "rowgroup", "colgroup"})
_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_INLINE_SPACE = re.compile(r"[ \t\f\v]+")


@dataclass(frozen=True, slots=True)
class HtmlView:
    html: str
    text: str


def _safe_href(value: str) -> str | None:
    compact = _CONTROL_OR_SPACE.sub("", value)
    try:
        parts = urlsplit(compact)
    except ValueError:
        return None
    if parts.scheme.lower() not in LINK_SCHEMES:
        return None
    if parts.scheme.lower() != "mailto" and not parts.netloc:
        return None
    return compact


def _safe_attribute(tag: str, name: str, value: str | None) -> str | None:
    if value is None or len(value) > MAX_ATTRIBUTE_CHARS:
        return None
    if name == "href":
        return _safe_href(value)
    if name in {"colspan", "rowspan", "start", "span"}:
        return value.strip() if _NUMBER.fullmatch(value.strip()) else None
    if name == "scope":
        return value.strip().lower() if value.strip().lower() in _SCOPES else None
    return remove_unsafe_chars(value, allow_line_breaks=False)


class _Renderer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.text: list[str] = []
        self.open: list[str] = []
        self.dropping: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closes=tag in VOID_TAGS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, closes=True)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, closes: bool) -> None:
        if self.dropping:
            if tag in DROPPED_WITH_CONTENT and not closes and tag not in VOID_TAGS:
                self.dropping.append(tag)
            return
        if tag in DROPPED_WITH_CONTENT:
            if not closes and tag not in VOID_TAGS:
                self.dropping.append(tag)
            return
        if tag in BLOCK_TAGS:
            self.text.append("\n")
        if tag not in ALLOWED_TAGS or (not closes and len(self.open) >= MAX_DEPTH):
            return
        rendered = [tag]
        allowed = ALLOWED_ATTRIBUTES.get(tag, frozenset())
        for name, value in attrs:
            safe = _safe_attribute(tag, name, value) if name in allowed else None
            if safe is not None:
                rendered.append(f'{name}="{html.escape(safe, quote=True)}"')
        if tag == "a" and any(part.startswith("href=") for part in rendered):
            rendered.append('rel="noopener noreferrer nofollow" target="_blank"')
        self.out.append(f"<{' '.join(rendered)}>")
        if not closes and tag not in VOID_TAGS:
            self.open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.dropping:
            if tag == self.dropping[-1]:
                self.dropping.pop()
            return
        if tag in BLOCK_TAGS:
            self.text.append("\n")
        if tag not in self.open:
            return
        while self.open:
            closed = self.open.pop()
            self.out.append(f"</{closed}>")
            if closed == tag:
                return

    def handle_data(self, data: str) -> None:
        if self.dropping:
            return
        safe = remove_unsafe_chars(data, allow_line_breaks=True)
        self.out.append(html.escape(safe, quote=False))
        self.text.append(safe)

    def close_all(self) -> None:
        while self.open:
            self.out.append(f"</{self.open.pop()}>")


def _plain(chunks: list[str]) -> str:
    lines = (_INLINE_SPACE.sub(" ", line).strip() for line in "".join(chunks).replace("\r", "").split("\n"))
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def render_html_view(source: str) -> HtmlView:
    renderer = _Renderer()
    renderer.feed(source)
    renderer.close()
    renderer.close_all()
    return HtmlView(html="".join(renderer.out), text=_plain(renderer.text))


__all__ = ["ALLOWED_ATTRIBUTES", "ALLOWED_TAGS", "HtmlView", "render_html_view"]
