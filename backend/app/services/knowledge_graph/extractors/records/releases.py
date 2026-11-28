"""Release records (e.g. Jira versions) as release nodes linked to their tracker."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...store import upsert_edge, upsert_node
from ..common import slugify


def _release_texts(release: dict[str, Any], name: str, project_key: str, released: bool) -> tuple[str, str]:
    release_date = str(release.get("release_date") or "").strip()
    start_date = str(release.get("start_date") or "").strip()
    description = str(release.get("description") or "").strip()

    status_line = (
        ("Released" + (f" on {release_date}" if release_date else ""))
        if released
        else ("Planned" + (f" for {release_date}" if release_date else ""))
    )
    parts = [f"Release {name}" + (f" of {project_key}" if project_key else "")]
    if description:
        parts.append(description)
    parts.append(status_line)
    if start_date:
        parts.append(f"Started {start_date}")
    return status_line, ". ".join(parts) + "."


async def _link_tracker(
    db: AsyncSession, *, project_id: str | None, release_node: Any, name: str, project_key: str, source_ref: str
) -> None:
    from ...store import resolve_node_by_alias

    tracker = await resolve_node_by_alias(db, project_id=project_id, alias=project_key)
    if tracker is None:
        tracker = await upsert_node(
            db,
            project_id=project_id,
            node_type="system",
            node_key=slugify(f"tracker-{project_key}"),
            display_name=project_key,
            description=f"Tracker project {project_key}",
            aliases=[project_key],
        )
    await upsert_edge(
        db,
        project_id=project_id,
        edge_type="part_of",
        source_node_id=release_node.id,
        target_node_id=tracker.id,
        description=f"Release {name} part of {project_key}",
        source_refs=[source_ref],
    )


async def ingest_release_record(
    db: AsyncSession,
    *,
    project_id: str | None,
    release: dict[str, Any],
) -> Any | None:
    """Map a release record (e.g. a Jira version) into the graph: a release node, its tracker project and a dated
    version claim."""
    name = str(release.get("name") or "").strip()
    if not name:
        return None
    project_key = str(release.get("project_key") or "").strip()
    source_ref = f"release:{project_key}:{name}" if project_key else f"release:{name}"
    released = bool(release.get("released"))
    release_date = str(release.get("release_date") or "").strip()
    status_line, node_description = _release_texts(release, name, project_key, released)
    release_node = await upsert_node(
        db,
        project_id=project_id,
        node_type="release",
        node_key=slugify(f"release-{project_key}-{name}"),
        display_name=name,
        description=node_description,
        aliases=[name],
        properties={
            "project_key": project_key,
            "released": released,
            "release_date": release_date or None,
        },
        source_refs=[source_ref],
        # Release names like "1.0" or "rs_2" repeat across trackers; identity
        # comes from the project-scoped key.
        resolve_by_alias=False,
    )
    from ...store import replace_claims_of_type

    # A release re-sync updates the status (planned -> released); supersede.
    await replace_claims_of_type(
        db,
        project_id=project_id,
        subject_node_id=release_node.id,
        claim_type="release",
        claims=[
            {
                "statement": f"Release {name}"
                + (f" of {project_key}" if project_key else "")
                + f": {status_line}",
                "valid_from_label": name,
                "source_refs": [source_ref],
            }
        ],
    )
    if project_key:
        await _link_tracker(
            db, project_id=project_id, release_node=release_node, name=name, project_key=project_key,
            source_ref=source_ref,
        )
    return release_node
