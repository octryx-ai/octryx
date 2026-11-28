"""The content assertions of a confirmed publication card: every body section and every criterion id."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from typing import Any

from ..platform.dispatch import CLASS_INVALID
from .audience_contract import (
    CODE_BINDING,
    CRITERIA_HEADING,
    LINKS_HEADING,
    MAX_ASSERTIONS,
    MAX_LINK_ITEMS,
    MAX_QUERY_CHARS,
    PROBE_WORDS,
    AudienceProofError,
)


class _Sections(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[tuple[str, list[str]]] = []
        self._heading: list[str] | None = None
        self.link_lists: dict[int, dict[str, Any]] = {}
        self._links: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "h2":
            self._finish_links()
            self._links = None
            self._heading = []
        elif self._links is not None:
            link = self._links
            stack = link["stack"]
            if tag in {"ul", "ol"}:
                link["bad"] |= bool(stack) or link["seen"]
                link["seen"] = True
                stack.append(tag)
            elif tag == "li":
                link["bad"] |= len(stack) != 1 or stack[0] not in {"ul", "ol"}
                link["seen"] = True
                link["item"] = []
                link["li_count"] += 1
                link["bad"] |= link["li_count"] > MAX_LINK_ITEMS
                stack.append(tag)
            elif stack:
                link["bad"] |= "li" not in stack or tag not in {"a", "b", "strong", "i", "em", "span", "code", "br"}
                if tag == "br":
                    link["item"].append(" ")
                else:
                    stack.append(tag)
            link["bad"] |= len(stack) > 8
            if link["bad"]:
                self._finish_links()

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._heading is not None:
            self.sections.append((" ".join("".join(self._heading).split()), []))
            self._heading = None
            if normalized(self.sections[-1][0]) == LINKS_HEADING:
                self._links = {"stack": [], "item": [], "items": [], "seen": False, "bad": False,
                               "outside": False, "li_count": 0}
                self.link_lists[len(self.sections) - 1] = self._links
        elif self._links is not None and (self._links["stack"] or tag in {"ul", "ol", "li"}):
            link = self._links
            if tag == "br":
                return
            if not link["stack"] or link["stack"][-1] != tag:
                link["bad"] = True
                self._finish_links()
                return
            link["stack"].pop()
            if tag == "li":
                text = " ".join("".join(link["item"]).split())
                if text:
                    link["items"].append(text)
                link["bad"] |= len(link["items"]) > MAX_LINK_ITEMS
                if link["bad"]:
                    self._finish_links()

    def _finish_links(self) -> None:
        link = self._links
        if link is not None and link["seen"]:
            if (link["bad"] or link["stack"] or link["outside"] or (link["li_count"] and not link["items"])
                    or len(" ".join(link["items"])) > MAX_QUERY_CHARS):
                raise AudienceProofError(CODE_BINDING, "the approved Links list is malformed or exceeds its bounds",
                                         failure_class=CLASS_INVALID)

    def close(self) -> None:
        super().close()
        self._finish_links()

    def handle_data(self, data: str) -> None:
        if self._heading is not None:
            self._heading.append(data)
        elif self.sections:
            self.sections[-1][1].append(data)
            if self._links is not None:
                link = self._links
                if "li" in link["stack"]:
                    link["item"].append(data)
                    link["bad"] |= sum(map(len, link["item"])) > MAX_QUERY_CHARS
                    if link["bad"]:
                        self._finish_links()
                elif data.strip():
                    link["outside"] = True


def normalized(text: object) -> str:
    return " ".join(unescape(str(text or "")).split()).lower()


def _words(text: str, count: int) -> str:
    return " ".join(text.split()[:count])


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "section"


def derive_query_set(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        raise AudienceProofError(CODE_BINDING, "the confirmed publication card carries no body",
                                 failure_class=CLASS_INVALID)
    parser = _Sections()
    parser.feed(body)
    parser.close()
    assertions: list[dict[str, Any]] = []
    for index, (heading, parts) in enumerate(parser.sections):
        text = " ".join(" ".join(parts).split())
        if not text or normalized(heading) == CRITERIA_HEADING:
            continue
        links = parser.link_lists.get(index)
        expect = ([normalized(item) for item in links["items"]] if links and links["seen"]
                  else [normalized(_words(text, PROBE_WORDS))])
        assertions.append({"id": f"section:{_slug(heading)}", "kind": "section", "heading": heading,
                           "query": text[:MAX_QUERY_CHARS], "expect": expect})
    if not assertions:
        raise AudienceProofError(CODE_BINDING, "the confirmed publication body has no section to prove",
                                 failure_class=CLASS_INVALID)
    for criterion in payload.get("acceptance_criteria") or []:
        if not isinstance(criterion, dict) or not str(criterion.get("id") or "").strip():
            continue
        ident, text = str(criterion["id"]).strip(), " ".join(str(criterion.get("text") or "").split())
        expect = [normalized(ident)] + ([normalized(_words(text, PROBE_WORDS))] if text else [])
        assertions.append({"id": f"criterion:{ident}", "kind": "criterion", "query": f"{ident} {text}"
                           .strip()[:MAX_QUERY_CHARS], "expect": expect})
    if len(assertions) > MAX_ASSERTIONS:
        raise AudienceProofError(CODE_BINDING, f"the confirmed publication has more than {MAX_ASSERTIONS} "
                                 "assertions", failure_class=CLASS_INVALID)
    return assertions
