from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ...tools.markup import html_to_markdown
from ..error_facts import error_text

LIT_SUFFIXES = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm"}


@dataclass(slots=True)
class ParsedDocument:
    parsed_path: Path
    text: str
    parser: str
    success: bool
    error: str = ""


_TEXT_MEDIA_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/xml",
    "text/xml",
}


def parse_document_file(
    file_path: Path,
    *,
    parsed_dir: Path,
    media_type: str = "",
    max_pages: int = 200,
    no_ocr: bool = True,
    timeout_sec: int = 180,
) -> ParsedDocument:
    suffix = file_path.suffix.lower()
    normalized_media_type = str(media_type or "").split(";", 1)[0].strip().lower()
    parsed_path = (parsed_dir / f"{file_path.stem}.parsed.txt").resolve()
    treat_as_html = normalized_media_type in {"text/html", "application/xhtml+xml"}
    treat_as_text = normalized_media_type in _TEXT_MEDIA_TYPES
    if suffix in TEXT_SUFFIXES or treat_as_html or treat_as_text:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        parser = "text"
        if suffix in {".html", ".htm"} or treat_as_html:
            text = html_to_markdown(text)
            parser = "html_markdown"
        parsed_path.write_text(text, encoding="utf-8")
        return ParsedDocument(parsed_path=parsed_path, text=text, parser=parser, success=True)
    if suffix not in LIT_SUFFIXES:
        return ParsedDocument(
            parsed_path=parsed_path,
            text="",
            parser="unsupported",
            success=False,
            error=f"Unsupported document suffix: {suffix or '(none)'}",
        )
    return _parse_with_lit(
        file_path, parsed_dir=parsed_dir, parsed_path=parsed_path, max_pages=max_pages, no_ocr=no_ocr,
        timeout_sec=timeout_sec,
    )


def _parse_with_lit(
    file_path: Path, *, parsed_dir: Path, parsed_path: Path, max_pages: int, no_ocr: bool, timeout_sec: int
) -> ParsedDocument:
    command = [
        "lit",
        "parse",
        "-o",
        str(parsed_path),
        "--format",
        "text",
        "--max-pages",
        str(max(1, int(max_pages or 200))),
    ]
    if no_ocr:
        command.append("--no-ocr")
    command.append(str(file_path))
    try:
        completed = subprocess.run(
            command,
            cwd=str(parsed_dir.parent),
            capture_output=True,
            text=True,
            timeout=max(5, int(timeout_sec or 180)),
            check=False,
        )
    except FileNotFoundError:
        return ParsedDocument(
            parsed_path=parsed_path, text="", parser="lit", success=False, error="lit executable not found"
        )
    except subprocess.TimeoutExpired as exc:
        return ParsedDocument(
            parsed_path=parsed_path,
            text="",
            parser="lit",
            success=False,
            error=error_text("lit_parse_timed_out", exc),
        )
    if completed.returncode != 0:
        # lit's stderr/stdout can quote the source path and document fragments: exit status only.
        return ParsedDocument(
            parsed_path=parsed_path,
            text="",
            parser="lit",
            success=False,
            error=f"lit_parse_failed exit_code={completed.returncode}",
        )
    # On success without an output file, stdout is the parsed document itself (the same content
    # the output file would hold), not process diagnostics.
    text = parsed_path.read_text(encoding="utf-8", errors="replace") if parsed_path.exists() else completed.stdout
    if not parsed_path.exists():
        parsed_path.write_text(text, encoding="utf-8")
    return ParsedDocument(parsed_path=parsed_path, text=text, parser="lit", success=True)
