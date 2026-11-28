"""The reading-order walk of a DoclingDocument body into :class:`Block` items (see ``docling_document.py``)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ....models.project.knowledge_parsing import (
    SPAN_KIND_CODE,
    SPAN_KIND_HEADING,
    SPAN_KIND_LIST,
    SPAN_KIND_TABLE,
    SPAN_KIND_TEXT,
)
from .docling_items import (
    _COLLECTIONS,
    _SKIPPED_LABELS,
    _TEXT_LABELS,
    ADMONITION_MARKERS,
    MAX_ADMONITION_CHARS,
    MAX_DOCUMENT_NODES,
    MAX_HEADING_CHARS,
    MAX_SECTION_DEPTH,
    MAX_TREE_DEPTH,
    NAVIGATION_LINK_SHARE,
    NAVIGATION_MIN_ITEMS,
    Block,
    _admonition_pattern,
    _clean,
    _contract,
    _page,
    _table_text,
    _top,
    _vocabulary,
)
from .outline_sections import outline_index


class _Walker:
    def __init__(self, document: dict[str, Any], admonitions: tuple[str, ...] = ADMONITION_MARKERS) -> None:
        self._document = document
        self._admonition = _admonition_pattern(admonitions) if admonitions else None
        self._vocabulary = _vocabulary(document)
        self._headings: list[tuple[int, str]] = []
        self._visited: set[str] = set()
        self.blocks: list[Block] = []

    def _resolve(self, ref: object) -> dict[str, Any]:
        if not isinstance(ref, dict) or type(ref.get("$ref")) is not str:
            raise _contract("ref")
        parts = ref["$ref"].split("/")
        if len(parts) != 3 or parts[0] != "#" or parts[1] not in _COLLECTIONS or not parts[2].isdigit():
            raise _contract("ref")
        collection = self._document.get(parts[1])
        index = int(parts[2])
        if not isinstance(collection, list) or index >= len(collection) or not isinstance(collection[index], dict):
            raise _contract("ref")
        return collection[index]

    def _path(self) -> tuple[str, ...]:
        return tuple(text for _, text in self._headings[:MAX_SECTION_DEPTH])

    def _emit(self, kind: str, text: str, item: dict[str, Any]) -> None:
        if text:
            top = _top(item, self._document.get("pages"))
            self.blocks.append(Block(kind=kind, text=text, page=_page(item), section_path=self._path(), top=top))

    def _heading(self, level: int, item: dict[str, Any]) -> None:
        text = _clean(item.get("text"))[:MAX_HEADING_CHARS].rstrip()
        if not text:
            return
        if level >= 1 and self._admonition is not None and len(text) <= MAX_ADMONITION_CHARS:
            if self._admonition.fullmatch(text):
                self._emit(SPAN_KIND_TEXT, text, item)  # a note box, not a section: keeps the enclosing one
                return
        while self._headings and self._headings[-1][0] >= level:
            self._headings.pop()
        self._headings.append((level, text))
        self._emit(SPAN_KIND_HEADING, text, item)

    def _captions(self, item: dict[str, Any], depth: int) -> None:
        for ref in item.get("captions") or ():
            self.walk(ref, depth + 1)

    def walk(self, ref: object, depth: int = 0) -> None:
        if depth > MAX_TREE_DEPTH:
            raise _contract("depth")
        key = ref.get("$ref") if isinstance(ref, dict) else None
        if key in self._visited:
            return  # every item is emitted once, whichever parent reaches it first
        item = self._resolve(ref)
        self._visited.add(key)
        if len(self._visited) > MAX_DOCUMENT_NODES:
            raise _contract("size")
        if item.get("content_layer", "body") != "body":
            return
        label = item.get("label")
        if label in _SKIPPED_LABELS or (label == "list" and self._is_site_navigation(item)):
            return
        if label == "title":
            self._heading(0, item)
        elif label == "section_header":
            level = item.get("level")
            self._heading(level if type(level) is int and level >= 1 else 1, item)
        elif label == "list_item":
            marker = _clean(item.get("marker")) or "-"
            text = _clean(item.get("text")) or " ".join(
                self._inline_text(self._resolve(ref), depth + 1)
                for ref in item.get("children") or ()
                if self._resolve(ref).get("label") == "inline"
            )
            self._emit(SPAN_KIND_LIST, f"{marker} {text}" if text else "", item)
            # HTML wraps an item's text in its own paragraph (Confluence: <li><p>text</p></li>); that child
            # says what the item already said, so it is not emitted a second time.
            for child in item.get("children") or ():
                node = self._resolve(child)
                if node.get("label") in _TEXT_LABELS and text and _clean(node.get("text")) == text:
                    self._visited.add(child.get("$ref") if isinstance(child, dict) else None)
        elif label == "code":
            self._emit(SPAN_KIND_CODE, _clean(item.get("text"), keep_lines=True), item)
        elif label == "table":
            self._captions(item, depth)
            self._emit(SPAN_KIND_TABLE, _table_text(item, self._vocabulary), item)
            return  # a table's children are its captions, already emitted
        elif label in ("picture", "chart"):
            self._captions(item, depth)
            return  # diagram labels inside a picture are noise, its captions are not
        elif label in _TEXT_LABELS:
            self._emit(SPAN_KIND_TEXT, _clean(item.get("text")), item)
        elif label == "inline":
            # One sentence split into text and code runs: kept whole, code in backticks, so a name such
            # as `@JsonComponent` stays inside the sentence that says what happened to it.
            self._emit(SPAN_KIND_TEXT, self._inline_text(item, depth), item)
            return
        for child in item.get("children") or ():
            self.walk(child, depth + 1)

    def _is_site_navigation(self, group: dict[str, Any]) -> bool:
        refs = [ref for ref in group.get("children") or () if isinstance(ref, dict)]
        if len(refs) < NAVIGATION_MIN_ITEMS:
            return False
        internal = 0
        for ref in refs:
            item = self._resolve(ref)
            link = str(item.get("hyperlink") or "")
            if item.get("label") == "list_item" and link.startswith(("/", "#")):
                internal += 1
        return internal >= NAVIGATION_LINK_SHARE * len(refs)

    def _inline_text(self, item: dict[str, Any], depth: int) -> str:
        parts: list[str] = []
        for ref in item.get("children") or ():
            if depth > MAX_TREE_DEPTH:
                raise _contract("depth")
            child = self._resolve(ref)
            self._visited.add(ref.get("$ref"))
            text = _clean(child.get("text"))
            if child.get("label") == "inline":
                text = self._inline_text(child, depth + 1)
            if text:
                parts.append(f"`{text}`" if child.get("label") == "code" else text)
        return _clean(" ".join(parts).replace(" ,", ",").replace(" .", "."))


def _text_volume(walker: _Walker, ref: object, depth: int = 0) -> int:
    if depth > MAX_TREE_DEPTH:
        raise _contract("depth")
    item = walker._resolve(ref)
    if item.get("content_layer", "body") != "body":
        return 0
    return len(str(item.get("text") or "")) + sum(
        _text_volume(walker, child, depth + 1) for child in item.get("children") or ()
    )


def _main_content(walker: _Walker, children: list) -> list:
    volumes = [_text_volume(walker, child) for child in children]
    total = sum(volumes)
    if not total:
        return children
    best = max(range(len(children)), key=lambda index: volumes[index])
    return [children[best]] if volumes[best] * 2 >= total else children


def document_blocks(
    document: object, *, admonitions: tuple[str, ...] = ADMONITION_MARKERS, outline: object = None
) -> list[Block]:
    if not isinstance(document, dict) or not isinstance(document.get("body"), dict):
        raise _contract("document")
    walker = _Walker(document, admonitions)
    children = list(document["body"].get("children") or ())
    origin = document.get("origin") if isinstance(document.get("origin"), dict) else {}
    if origin.get("mimetype") == "text/html":
        children = _main_content(walker, children)
    for child in children:
        walker.walk(child)
    # Docling reports every heading of a vendor manual at level 1; the PDF outline has the real hierarchy.
    index = outline_index(outline)
    if index is None:
        return walker.blocks
    return [replace(block, section_path=index.path_at(block.page, block.top) or block.section_path)
            for block in walker.blocks]
