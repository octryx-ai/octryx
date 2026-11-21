"""Trace link payloads the sync runners create for a matched release or checkpoint."""

from __future__ import annotations

from typing import Any


def release_link_payload(artifact: dict[str, Any], release: dict[str, Any], repo_name: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact["id"],
        "target_type": "release",
        "target_id": str(release.get("external_id") or ""),
        "title": str(release.get("title") or release.get("tag_name") or "Release"),
        "status": str(release.get("state") or "completed"),
        "url": str(release.get("url") or ""),
        "metadata_json": {
            "auto_synced": True,
            "source": "release_sync",
            "provider": release.get("provider"),
            "repository_name": release.get("repository_name") or repo_name,
            "number": release.get("number"),
            "tag_name": release.get("tag_name"),
            "object_kind": release.get("object_kind") or "release",
        },
    }


def checkpoint_link_payload(artifact: dict[str, Any], checkpoint: dict[str, Any], repo_name: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact["id"],
        "target_type": "checkpoint",
        "target_id": str(checkpoint.get("external_id") or ""),
        "title": str(checkpoint.get("title") or checkpoint.get("external_id") or "Checkpoint"),
        "status": str(checkpoint.get("state") or "completed"),
        "url": str(checkpoint.get("url") or ""),
        "metadata_json": {
            "auto_synced": True,
            "source": "checkpoint_sync",
            "provider": checkpoint.get("provider"),
            "repository_name": checkpoint.get("repository_name") or repo_name,
            "number": checkpoint.get("number"),
            "object_kind": checkpoint.get("object_kind"),
            "branch": checkpoint.get("branch"),
            "head_sha": checkpoint.get("head_sha"),
            "event": checkpoint.get("event"),
            "conclusion": checkpoint.get("conclusion"),
        },
    }


def link_key(artifact: dict[str, Any], target_type: str, item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (artifact["id"], target_type, str(item.get("external_id") or ""), str(item.get("url") or ""))
