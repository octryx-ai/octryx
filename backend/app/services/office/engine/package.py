"""Opening and saving Office packages: kind detection, template → document conversion, atomic writes."""

from __future__ import annotations

import io
import os
import tempfile
import warnings
import zipfile
from pathlib import Path
from typing import Any

from .paths import DOCUMENT_UNREADABLE, FILE_NOT_FOUND, INVALID_REQUEST, OfficeEngineError

KIND_BY_SUFFIX = {
    ".docx": "docx",
    ".docm": "docx",
    ".dotx": "docx",
    ".pptx": "pptx",
    ".pptm": "pptx",
    ".potx": "pptx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xltx": "xlsx",
}
TEMPLATE_SUFFIXES = {".dotx", ".potx", ".xltx"}

#: Template main-part content type → document main-part content type, per kind.
_TEMPLATE_CONTENT_TYPES = {
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    ),
    "pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    ),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    ),
}


def document_kind(path: str | Path, doc_type: str = "") -> str:
    requested = str(doc_type or "").strip().lower().lstrip(".")
    if requested in {"docx", "pptx", "xlsx"}:
        return requested
    kind = KIND_BY_SUFFIX.get(Path(path).suffix.lower())
    if kind is None:
        raise OfficeEngineError(INVALID_REQUEST, "only .docx, .pptx and .xlsx documents are supported")
    return kind


def existing_file(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.is_file():
        raise OfficeEngineError(FILE_NOT_FOUND, resolved.name)
    return resolved


def is_template(path: str | Path) -> bool:
    return Path(path).suffix.lower() in TEMPLATE_SUFFIXES


#: Package guards, checked before any member is decompressed or parsed (zip bombs, oversized documents).
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 4000
MAX_COMPRESSION_RATIO = 100
_RATIO_FLOOR_BYTES = 1024 * 1024


def check_package(archive: zipfile.ZipFile) -> None:
    members = archive.infolist()
    if len(members) > MAX_MEMBERS:
        raise OfficeEngineError(DOCUMENT_UNREADABLE, f"package has more than {MAX_MEMBERS} parts")
    total = sum(item.file_size for item in members)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise OfficeEngineError(DOCUMENT_UNREADABLE, "package expands beyond the size limit")
    for item in members:
        if item.file_size > _RATIO_FLOOR_BYTES and item.file_size > MAX_COMPRESSION_RATIO * max(item.compress_size, 1):
            raise OfficeEngineError(DOCUMENT_UNREADABLE, "package part compression ratio is out of bounds")
    compressed = sum(item.compress_size for item in members)
    if total > _RATIO_FLOOR_BYTES and total > MAX_COMPRESSION_RATIO * max(compressed, 1):
        raise OfficeEngineError(DOCUMENT_UNREADABLE, "package compression ratio is out of bounds")


def document_bytes(path: str | Path) -> bytes:
    source = existing_file(path)
    if source.stat().st_size > MAX_PACKAGE_BYTES:
        raise OfficeEngineError(DOCUMENT_UNREADABLE, "file is larger than the size limit")
    data = source.read_bytes()
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise OfficeEngineError(DOCUMENT_UNREADABLE, "not an Office Open XML package")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            check_package(archive)
    except zipfile.BadZipFile as exc:
        raise OfficeEngineError(DOCUMENT_UNREADABLE, "damaged package") from exc
    kind = KIND_BY_SUFFIX.get(source.suffix.lower())
    if kind is None:
        return data
    template_type, document_type = _TEMPLATE_CONTENT_TYPES[kind]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        content_types = archive.read("[Content_Types].xml").decode("utf-8")
        if template_type not in content_types:
            return data
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as rebuilt:
            for item in archive.infolist():
                payload = archive.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    payload = content_types.replace(template_type, document_type).encode("utf-8")
                rebuilt.writestr(item, payload)
    return output.getvalue()


def open_document(path: str | Path, kind: str) -> Any:
    stream = io.BytesIO(document_bytes(path))
    try:
        if kind == "docx":
            import docx

            return docx.Document(stream)
        if kind == "pptx":
            import pptx

            return pptx.Presentation(stream)
        import openpyxl

        with warnings.catch_warnings():
            # openpyxl drops the sparkline extension with a warning; api.Opened carries sparklines itself.
            warnings.filterwarnings("ignore", message="Sparkline Group extension", category=UserWarning)
            workbook = openpyxl.load_workbook(stream)
        workbook.template = False
        return workbook
    except OfficeEngineError:
        raise
    except Exception as exc:  # the libraries raise many unrelated types for a damaged package
        raise OfficeEngineError(DOCUMENT_UNREADABLE, type(exc).__name__) from exc


def new_document(kind: str) -> Any:
    if kind == "docx":
        import docx

        return docx.Document()
    if kind == "pptx":
        import pptx

        return pptx.Presentation()
    import openpyxl

    return openpyxl.Workbook()


def save_document(document: Any, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    os.close(handle)
    try:
        document.save(temp_name)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target


__all__ = [
    "KIND_BY_SUFFIX",
    "MAX_COMPRESSION_RATIO",
    "MAX_MEMBERS",
    "MAX_PACKAGE_BYTES",
    "MAX_UNCOMPRESSED_BYTES",
    "check_package",
    "TEMPLATE_SUFFIXES",
    "document_bytes",
    "document_kind",
    "existing_file",
    "is_template",
    "new_document",
    "open_document",
    "save_document",
]
