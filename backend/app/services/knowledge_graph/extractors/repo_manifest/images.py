"""Container image references and their shared graph nodes."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import upsert_node
from ..common import slugify


def _normalized_image(ref: str) -> str:
    """'registry.host/ns/name:tag@digest' -> 'ns/name' (registry host and tag stripped)."""
    value = str(ref or "").strip().split("@", 1)[0]
    if not value:
        return ""
    # Drop the tag, but not a port in the registry host (host:port/...).
    if ":" in value.rsplit("/", 1)[-1]:
        value = value.rsplit(":", 1)[0]
    segments = [seg for seg in value.split("/") if seg]
    if len(segments) > 1 and ("." in segments[0] or ":" in segments[0]):
        segments = segments[1:]
    return "/".join(segments[-2:]) if len(segments) > 1 else (segments[0] if segments else "")


async def _upsert_image_node(db: AsyncSession, *, project_id: str | None, image: str, source_ref: str) -> Any:
    basename = image.rsplit("/", 1)[-1]
    return await upsert_node(
        db,
        project_id=project_id,
        node_type="container_image",
        node_key=slugify(f"img-{image}"),
        display_name=image,
        description=f"Container image {image}",
        aliases=[value for value in {image, basename} if value],
        source_refs=[source_ref],
        resolve_by_alias=False,
    )
