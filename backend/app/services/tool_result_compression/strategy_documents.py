from __future__ import annotations

from typing import Any

from app.services.tool_result_compression.config import build_truncated_excerpt, clamp_config_int


def _compact_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": source.get("id"),
        "title": source.get("title"),
        "url": source.get("url"),
        "origin": source.get("origin"),
        "file_name": source.get("file_name"),
        "suffix": source.get("suffix"),
        "media_type": source.get("media_type"),
        "source_type": source.get("source_type"),
        "publisher": source.get("publisher"),
        "year": source.get("year"),
        "local_relative_path": source.get("local_relative_path"),
        "parsed_relative_path": source.get("parsed_relative_path"),
        "evidence_record_relative_path": source.get("evidence_record_relative_path"),
        "evidence_manifest_relative_path": source.get("evidence_manifest_relative_path"),
        "parse_success": source.get("parse_success"),
        "parse_error": source.get("parse_error"),
        "bundle_id": source.get("bundle_id"),
        "citation_style": source.get("citation_style"),
    }


def _compress_document_ingest(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    source = result.get("source") if isinstance(result.get("source"), dict) else {}
    max_artifacts = clamp_config_int(config, "max_artifacts", default=8, minimum=1, maximum=30)
    max_preview_chars = clamp_config_int(config, "max_preview_chars", default=1200, minimum=0, maximum=4000)
    artifacts: list[dict[str, Any]] = []
    for artifact in list(result.get("artifacts") or [])[:max_artifacts]:
        if not isinstance(artifact, dict):
            continue
        artifacts.append(
            {
                "path": artifact.get("path"),
                "name": artifact.get("name"),
                "media_type": artifact.get("media_type"),
                "size_bytes": artifact.get("size_bytes"),
            }
        )
    return {
        "success": bool(result.get("success", True)),
        "bundle_id": result.get("bundle_id"),
        "bundle_path": result.get("bundle_path"),
        "sources_path": result.get("sources_path"),
        "citations_path": result.get("citations_path"),
        "evidence_manifest_path": result.get("evidence_manifest_path"),
        "evidence_record_path": result.get("evidence_record_path"),
        "sources_count": result.get("sources_count"),
        "citations_count": result.get("citations_count"),
        "evidence_count": result.get("evidence_count"),
        "source": _compact_source(source),
        "artifacts": artifacts,
        "content_preview": build_truncated_excerpt(
            str(result.get("content_preview") or ""),
            max_chars=max_preview_chars,
        ),
    }


def _compact_source_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: candidate.get(key)
        for key in ("url", "title", "snippet")
        if str(candidate.get(key) or "").strip()
    }


def _compact_subthread_quality(quality: dict[str, Any], *, max_sources: int) -> dict[str, Any]:
    return {
        "profile": quality.get("profile"),
        "accepted": bool(quality.get("accepted")),
        "response_kind": quality.get("response_kind"),
        "rejection_reasons": list(quality.get("rejection_reasons") or []),
        "has_tool_evidence": bool(quality.get("has_tool_evidence")),
        "is_source_grounded": bool(quality.get("is_source_grounded")),
        "successful_tool_names": list(quality.get("successful_tool_names") or []),
        "credible_source_count": quality.get("credible_source_count"),
        "source_urls": list(quality.get("source_urls") or [])[:max_sources],
        "source_candidates": [
            _compact_source_candidate(candidate)
            for candidate in list(quality.get("source_candidates") or [])[:max_sources]
            if isinstance(candidate, dict)
        ],
        "credible_source_candidates": [
            _compact_source_candidate(candidate)
            for candidate in list(quality.get("credible_source_candidates") or [])[:max_sources]
            if isinstance(candidate, dict)
        ],
    }


def _compact_subthread(item: dict[str, Any], config: dict[str, Any], *, accepted: bool) -> dict[str, Any]:
    max_response_chars = clamp_config_int(config, "max_response_chars", default=480, minimum=0, maximum=2000)
    max_task_chars = clamp_config_int(config, "max_task_chars", default=220, minimum=40, maximum=1000)
    max_sources = clamp_config_int(config, "max_sources_per_thread", default=8, minimum=1, maximum=30)
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    compact = {
        "session_id": item.get("session_id"),
        "status": item.get("status"),
        "title": item.get("title"),
        "task": build_truncated_excerpt(str(item.get("task") or ""), max_chars=max_task_chars),
        "message_count": item.get("message_count"),
        "tool_call_count": item.get("tool_call_count"),
        "tool_names": list(item.get("tool_names") or []),
        "quality": _compact_subthread_quality(quality, max_sources=max_sources),
    }
    if accepted:
        compact["final_response"] = build_truncated_excerpt(
            str(item.get("final_response") or ""),
            max_chars=max_response_chars,
        )
        # The child's openable sources stay in the parent's evidence (answer_evidence.child_evidence).
        compact["evidence_sources"] = [
            source for source in list(item.get("evidence_sources") or [])[:max_sources] if isinstance(source, dict)
        ]
    return compact


def _compress_subthread_context(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_accepted = clamp_config_int(config, "max_accepted_subthreads", default=8, minimum=1, maximum=30)
    max_rejected = clamp_config_int(config, "max_rejected_subthreads", default=8, minimum=0, maximum=30)
    accepted_subthreads = [
        _compact_subthread(item, config, accepted=True)
        for item in list(result.get("accepted_subthreads") or result.get("subthreads") or [])[:max_accepted]
        if isinstance(item, dict)
    ]
    rejected_subthreads = [
        _compact_subthread(item, config, accepted=False)
        for item in list(result.get("rejected_subthreads") or [])[:max_rejected]
        if isinstance(item, dict)
    ]
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    return {
        "parent_session_id": result.get("parent_session_id"),
        "evidence_profile": result.get("evidence_profile"),
        "count": result.get("count"),
        "accepted_count": result.get("accepted_count"),
        "rejected_count": result.get("rejected_count"),
        "subthreads": accepted_subthreads,
        "accepted_subthreads": accepted_subthreads,
        "rejected_subthreads": rejected_subthreads,
        "summary": {
            "completed": summary.get("completed"),
            "failed": summary.get("failed"),
            "active": summary.get("active"),
            "accepted": summary.get("accepted"),
            "rejected": summary.get("rejected"),
            "tool_names": list(summary.get("tool_names") or []),
        },
    }
