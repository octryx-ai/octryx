"""``urls_cited``: the distinct http(s) URLs a phase cited in what it wrote."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase
from typing import Any

MAX_MIN_COUNT = 100
MAX_PATH_CHARS = 300
_URL = re.compile(r"https?://[^\s<>()\[\]{}\"'`|\\^]+", re.IGNORECASE)
_TRAILING = ".,;:!?*_~"
_WRITE_TOOLS = frozenset({"write_workspace_file", "edit_workspace_file", "multi_edit_workspace_file"})
_TEXT_KEYS = ("content", "new_string", "new_text")


def params_error(params: Any) -> str | None:
    if params is None:
        return None
    if not isinstance(params, Mapping) or set(params) - {"min_count", "path"}:
        return "urls_cited takes only min_count and path"
    minimum = params.get("min_count", 1)
    if type(minimum) is not int or not 1 <= minimum <= MAX_MIN_COUNT:
        return f"urls_cited.min_count must be an integer 1..{MAX_MIN_COUNT}"
    path = params.get("path")
    if path is not None and (not isinstance(path, str) or not path.strip() or len(path) > MAX_PATH_CHARS):
        return "urls_cited.path must be a non-empty glob"
    return None


def _platform_host() -> str:
    from ...config import get_settings

    origin = str(getattr(get_settings(), "platform_public_origin", "") or "")
    return origin.split("://", 1)[-1].split("/", 1)[0].lower() if origin else "-"


def distinct_urls(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in _URL.finditer(str(text or "")):
        url = match.group(0).rstrip(_TRAILING)
        host = url.split("://", 1)[1].split("/", 1)[0].lower()
        if re.fullmatch(r"https?://", url, re.IGNORECASE) or ("." not in host and host != _platform_host()):
            continue  # no host name (``http://`` alone, ``http://localhost``): no source; the platform's own is one
        seen.setdefault(url.rstrip("/"), None)
    return list(seen)


def added_lines(patch: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in str(patch or "").splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            current = None if target == "/dev/null" else target.removeprefix("b/")
            if current is not None:
                out.setdefault(current, [])
        elif line.startswith("diff --git "):
            current = None
        elif current is not None and line.startswith("+"):
            out[current].append(line[1:])
    return {path: "\n".join(lines) for path, lines in out.items()}


def tool_written_texts(uses: Iterable[Any]) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for use in uses:
        params = getattr(use, "params", None)
        if getattr(use, "name", "") not in _WRITE_TOOLS or not getattr(use, "succeeded", False) or not isinstance(
                params, Mapping):
            continue
        path = str(params.get("path") or params.get("file_path") or "")
        texts = [str(params[key]) for key in _TEXT_KEYS if isinstance(params.get(key), str)]
        texts += [str(edit.get(key)) for edit in params.get("edits") or [] if isinstance(edit, Mapping)
                  for key in _TEXT_KEYS if isinstance(edit.get(key), str)]
        if texts:
            out.setdefault(path, []).extend(texts)
    return {path: "\n".join(texts) for path, texts in out.items()}


def _matches(path: str, pattern: str) -> bool:
    pattern = pattern.strip().lstrip("/")
    path = path.lstrip("/")
    return fnmatchcase(path, pattern) or (pattern.startswith("**/") and fnmatchcase(path, pattern[3:]))


def evaluate_urls_cited(params: Mapping[str, Any], written: Mapping[str, str], answer: str) -> tuple[str, str]:
    from .library import FAILED, PASSED

    minimum = params.get("min_count") if type(params.get("min_count")) is int and params["min_count"] >= 1 else 1
    pattern = params.get("path") if isinstance(params.get("path"), str) and params["path"].strip() else None
    files = {path: text for path, text in written.items() if pattern is None or _matches(path, pattern)}
    if files:
        where = ", ".join(sorted(files)[:3]) + (" …" if len(files) > 3 else "")
        urls = distinct_urls("\n".join(files.values()))
    elif pattern is not None:
        return FAILED, f"no written file matches {pattern}: 0 of {minimum} source URLs"
    else:
        where, urls = "the answer", distinct_urls(answer)
    if len(urls) >= minimum:
        return PASSED, f"{len(urls)} distinct source URLs in {where}"
    return FAILED, f"{len(urls)} of {minimum} distinct source URLs cited in {where}"


__all__ = ["added_lines", "distinct_urls", "evaluate_urls_cited", "params_error", "tool_written_texts"]
