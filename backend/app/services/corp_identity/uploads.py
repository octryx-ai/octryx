"""Upload helpers for corporate identity panel routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..corp_identity_service import (
    _safe_upload_name,
    attach_example_deck_to_corp_identity_profile,
    save_uploaded_corp_identity_profile,
)

DEFAULT_UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


class CorpIdentityUploadTooLargeError(ValueError):
    pass


async def _read_stream_bounded(
    read_chunk: Callable[[int], Awaitable[bytes]],
    close_file: Callable[[], Awaitable[None]],
    *,
    safe_name: str,
    chunk_size: int,
    max_bytes: int,
) -> bytes:
    written = 0
    chunks: list[bytes] = []
    try:
        while True:
            chunk = await read_chunk(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                raise CorpIdentityUploadTooLargeError(f"File '{safe_name}' exceeds the 512 MB upload limit")
            chunks.append(chunk)
    finally:
        await close_file()
    return b"".join(chunks)


async def save_uploaded_corp_identity_profile_from_stream(
    db: AsyncSession,
    *,
    file_name: str,
    read_chunk: Callable[[int], Awaitable[bytes]],
    close_file: Callable[[], Awaitable[None]],
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
    max_bytes: int = MAX_UPLOAD_BYTES,
    merge_into_profile_id: str | None = None,
) -> dict[str, object]:
    safe_name = _safe_upload_name(file_name or "identity-template.potx")
    data = await _read_stream_bounded(
        read_chunk, close_file, safe_name=safe_name, chunk_size=chunk_size, max_bytes=max_bytes
    )
    return await save_uploaded_corp_identity_profile(
        db,
        file_name=safe_name,
        file_bytes=data,
        merge_into_profile_id=merge_into_profile_id,
    )


async def attach_example_deck_from_stream(
    db: AsyncSession,
    *,
    profile_id: str,
    file_name: str,
    read_chunk: Callable[[int], Awaitable[bytes]],
    close_file: Callable[[], Awaitable[None]],
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> dict[str, object]:
    safe_name = _safe_upload_name(file_name or "example.pptx")
    data = await _read_stream_bounded(
        read_chunk, close_file, safe_name=safe_name, chunk_size=chunk_size, max_bytes=max_bytes
    )
    return await attach_example_deck_to_corp_identity_profile(
        db, profile_id=profile_id, file_name=safe_name, file_bytes=data
    )


__all__ = [
    "CorpIdentityUploadTooLargeError",
    "DEFAULT_UPLOAD_CHUNK_SIZE",
    "MAX_UPLOAD_BYTES",
    "attach_example_deck_from_stream",
    "save_uploaded_corp_identity_profile_from_stream",
]
