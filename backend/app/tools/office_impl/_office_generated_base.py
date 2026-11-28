"""Shared helpers for generated Office script tools."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from ...services.error_facts import error_type
from ...services.office.engine import api as office_engine
from ...services.process_output_redaction import redact_process_output


def office_script_failure(
    code: str,
    *,
    script_path: Path,
    exit_code: int | None = None,
    exc: BaseException | None = None,
) -> dict[str, Any]:
    facts = [code]
    result: dict[str, Any] = {"error_code": code, "exit_code": exit_code, "script_path": str(script_path)}
    if exit_code is not None:
        facts.append(f"exit_code={exit_code}")
    if exc is not None:
        result["error_type"] = error_type(exc)
        facts.append(f"error_type={result['error_type']}")
    return {"error": " ".join(facts), **result}


def office_script_env(script_dir: Path) -> dict[str, str]:
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(script_dir), "LANG": "C.UTF-8"}


def office_script_command(script_path: Path) -> list[str]:
    return [sys.executable, "-I", str(script_path)]


async def run_office_script(script_path: Path, *, timeout_sec: int) -> tuple[dict[str, Any] | None, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *office_script_command(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(script_path.parent),
            env=office_script_env(script_path.parent),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"error": f"build script timed out after {timeout_sec} seconds", "script_path": str(script_path)}, "", ""
    except Exception as exc:
        return office_script_failure("office_script_not_started", script_path=script_path, exc=exc), "", ""
    if proc.returncode != 0:
        return office_script_failure("office_script_failed", script_path=script_path, exit_code=proc.returncode), "", ""
    return None, redact_process_output(stdout_bytes), stderr_bytes.decode("utf-8", errors="replace")


async def office_validation(output_path: Path) -> dict[str, Any]:
    result = await asyncio.to_thread(office_engine.validate, output_path)
    if result.get("error"):
        return {"valid": False, "error_code": result.get("error_code")}
    return dict(result.get("data") or {})


async def office_stats(output_path: Path) -> dict[str, Any]:
    result = await asyncio.to_thread(office_engine.view, output_path, "stats")
    if result.get("error"):
        return {"error": f"office_stats_failed {result.get('error_code')}", "error_code": "office_stats_failed"}
    return dict(result.get("data") or {})


def _json_script_literal(value: Any) -> str:
    return repr(json.dumps(value, ensure_ascii=False, default=str))


_WORD_CITATION_STYLES = {
    "none",
    "ieee",
    "apa",
    "mla",
    "chicago",
    "harvard",
}


def _normalize_word_citation_style(value: Any) -> str:
    style = str(value or "").strip().lower()
    return style if style in _WORD_CITATION_STYLES else "none"


_DOI_PATTERN = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)
_ISBN_PATTERN = re.compile(r"\b(?:97[89][- ]?)?\d[- \d]{8,16}\d\b")


def _clean_bibliography_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_author_list(raw_source: dict[str, Any]) -> list[str]:
    authors = raw_source.get("authors")
    if isinstance(authors, list):
        cleaned = [_clean_bibliography_text(item) for item in authors if _clean_bibliography_text(item)]
        if cleaned:
            return cleaned
    author = _clean_bibliography_text(raw_source.get("author"))
    if not author:
        return []
    if ";" in author:
        return [_clean_bibliography_text(item) for item in author.split(";") if _clean_bibliography_text(item)]
    if " and " in author.lower():
        return [
            _clean_bibliography_text(item)
            for item in re.split(r"\band\b", author, flags=re.IGNORECASE)
            if _clean_bibliography_text(item)
        ]
    return [author]


def _extract_doi(raw_source: dict[str, Any]) -> str:
    for candidate in (
        raw_source.get("doi"),
        raw_source.get("url"),
        raw_source.get("title"),
    ):
        match = _DOI_PATTERN.search(str(candidate or ""))
        if match:
            return match.group(1).rstrip(".,);]")
    return ""


def _extract_isbn(raw_source: dict[str, Any]) -> str:
    for candidate in (
        raw_source.get("isbn"),
        raw_source.get("title"),
    ):
        match = _ISBN_PATTERN.search(str(candidate or ""))
        if match:
            return re.sub(r"[^0-9Xx]", "", match.group(0)).upper()
    return ""


def _normalize_bibliography_sources(raw_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_source in enumerate(raw_sources, start=1):
        if not isinstance(raw_source, dict):
            continue
        title = _clean_bibliography_text(raw_source.get("title") or raw_source.get("name"))
        url = _clean_bibliography_text(raw_source.get("url") or raw_source.get("link"))
        doi = _extract_doi(raw_source)
        isbn = _extract_isbn(raw_source)
        dedupe_key = (
            f"doi:{doi.lower()}"
            if doi
            else f"isbn:{isbn}"
            if isbn
            else f"url:{url.lower()}"
            if url
            else f"title:{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')}"
        )
        if not title or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(
            {
                "id": _clean_bibliography_text(raw_source.get("id") or raw_source.get("key") or f"source-{index}"),
                "key": _clean_bibliography_text(raw_source.get("key") or raw_source.get("id") or f"source-{index}"),
                "title": title,
                "author": _clean_bibliography_text(raw_source.get("author")),
                "authors": _normalize_author_list(raw_source),
                "publisher": _clean_bibliography_text(raw_source.get("publisher") or raw_source.get("organization")),
                "organization": _clean_bibliography_text(raw_source.get("organization")),
                "url": url,
                "year": _clean_bibliography_text(raw_source.get("year") or ""),
                "published_at": _clean_bibliography_text(raw_source.get("published_at") or raw_source.get("date")),
                "accessed_at": _clean_bibliography_text(raw_source.get("accessed_at") or raw_source.get("accessed")),
                "doi": doi,
                "isbn": isbn,
                "source_type": _clean_bibliography_text(raw_source.get("source_type")),
            }
        )
    return normalized


class _GeneratedOfficeScriptToolBase:
    doc_type = ""
    script_timeout_sec = 300

    def _script_path_for_output(self, output_path: Path) -> Path:
        return output_path.parent / f"{output_path.name}.build.py"

    def _write_script(self, output_path: Path, script_content: str) -> Path:
        script_path = self._script_path_for_output(output_path)
        script_path.write_text(script_content, encoding="utf-8")
        return script_path

    async def _execute_script(self, script_path: Path) -> tuple[dict[str, Any] | None, str, str]:
        return await run_office_script(script_path, timeout_sec=self.script_timeout_sec)

    async def _validate_document(self, output_path: Path) -> dict[str, Any]:
        return await office_validation(output_path)

    async def _inspect_document_stats(self, output_path: Path) -> dict[str, Any]:
        return await office_stats(output_path)


__all__ = [
    "_GeneratedOfficeScriptToolBase",
    "_json_script_literal",
    "_normalize_bibliography_sources",
    "_normalize_word_citation_style",
    "office_script_command",
    "office_script_env",
    "office_script_failure",
    "office_stats",
    "office_validation",
    "run_office_script",
]
