"""Utilities for converting HTML into markdown/plain text."""

from __future__ import annotations

import html
import re


def _meaningful_text_length(value: str) -> int:
    return len(re.sub(r"\s+", " ", strip_html(value)).strip())


def _remove_tag_blocks(value: str, tags: tuple[str, ...]) -> str:
    text = value
    for tag in tags:
        text = re.sub(rf"(?is)<{tag}\b[^>]*>.*?</{tag}>", " ", text)
    return text


def _remove_attribute_matched_blocks(value: str) -> str:
    patterns = (
        "cookie",
        "consent",
        "breadcrumb",
        "promo",
        "newsletter",
        "subscribe",
        "social",
        "sidebar",
        "nav",
        "menu",
        "footer",
        "header",
        "modal",
        "popup",
        "banner",
    )
    joined = "|".join(patterns)
    text = value
    for tag in ("div", "section", "aside", "nav", "header", "footer"):
        text = re.sub(
            rf'(?is)<{tag}\b[^>]*(?:id|class)=["\'][^"\']*(?:{joined})[^"\']*["\'][^>]*>.*?</{tag}>',
            " ",
            text,
        )
    return text


def _extract_tag_fragment(value: str, tag: str) -> str:
    match = re.search(rf"(?is)<{tag}\b[^>]*>(.*?)</{tag}>", value)
    return match.group(1) if match else ""


def _extract_role_main_fragment(value: str) -> str:
    match = re.search(r'(?is)<([a-z0-9]+)\b[^>]*role=["\']main["\'][^>]*>(.*?)</\1>', value)
    return match.group(2) if match else ""


def _extract_content_attribute_fragment(value: str) -> str:
    patterns = (
        "article-body",
        "article-content",
        "blog-content",
        "blog-description",
        "post-content",
        "post-body",
        "entry-content",
        "content-body",
        "content-container",
        "richtext",
        "rich-text",
        "prose",
        "doc-content",
        "documentation-content",
    )
    joined = "|".join(patterns)
    matches = re.finditer(
        rf'(?is)<([a-z0-9]+)\b[^>]*(?:id|class)=["\'][^"\']*(?:{joined})[^"\']*["\'][^>]*>(.*?)</\1>',
        value,
    )
    best_fragment = ""
    best_length = 0
    for match in matches:
        fragment = match.group(2)
        length = _meaningful_text_length(fragment)
        if length > best_length:
            best_fragment = fragment
            best_length = length
    return best_fragment


def extract_main_html_fragment(value: str) -> str:
    text = re.sub(r"(?is)<!--.*?-->", " ", value or "")
    text = _remove_tag_blocks(text, ("script", "style", "noscript", "template"))
    body = _extract_tag_fragment(text, "body") or text
    candidates = [
        _extract_tag_fragment(body, "main"),
        _extract_tag_fragment(body, "article"),
        _extract_role_main_fragment(body),
        _extract_content_attribute_fragment(body),
    ]
    body_len = _meaningful_text_length(body)
    fragment = body
    for candidate in candidates:
        candidate_len = _meaningful_text_length(candidate)
        if candidate_len >= 120 or (body_len and candidate_len >= int(body_len * 0.25)):
            fragment = candidate
            break
    fragment = _remove_tag_blocks(fragment, ("nav", "aside", "footer", "form", "button"))
    fragment = _remove_attribute_matched_blocks(fragment)
    if _meaningful_text_length(fragment) < 80 and body_len > _meaningful_text_length(fragment):
        fallback = _remove_tag_blocks(body, ("nav", "aside", "footer", "form", "button"))
        fallback = _remove_attribute_matched_blocks(fallback)
        if _meaningful_text_length(fallback) > _meaningful_text_length(fragment):
            fragment = fallback
    return fragment.strip() or body.strip()


def _fallback_html_to_markdown(value: str) -> str:
    text = extract_main_html_fragment(value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|article|blockquote)>", "\n\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?i)</li>", "\n", text)
    for level in range(6, 0, -1):
        text = re.sub(
            rf"(?is)<h{level}[^>]*>(.*?)</h{level}>",
            lambda match: f"\n\n{'#' * level} {strip_html(match.group(1))}\n\n",
            text,
        )
    text = re.sub(
        r"(?is)<a[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        lambda m: f"[{strip_html(m.group(2))}]({m.group(1)})",
        text,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_html(value: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_markdown(value: str) -> str:
    normalized = extract_main_html_fragment(value)
    try:
        import html2text

        parser = html2text.HTML2Text()
        parser.body_width = 0
        parser.unicode_snob = True
        parser.ignore_images = True
        parser.ignore_emphasis = False
        parser.protect_links = True
        parser.single_line_break = False
        converted = parser.handle(normalized)
        converted = converted.replace("\r\n", "\n").strip()
        converted = re.sub(r"\n{3,}", "\n\n", converted)
        return converted
    except (ImportError, AttributeError, TypeError, ValueError):
        return _fallback_html_to_markdown(normalized)
