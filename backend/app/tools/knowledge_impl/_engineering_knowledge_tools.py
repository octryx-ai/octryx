from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select

from app.services.engineering_knowledge.source_ingestion_audit import audit_engineering_knowledge_source
from app.services.engineering_knowledge.source_ingestion_specs import EngineeringKnowledgeSourceSpec

from ...models import (
    EngineeringKnowledgePack,
    EngineeringKnowledgePackItem,
    EngineeringKnowledgePackSource,
    EngineeringKnowledgePackVersion,
)
from ...services.engineering_knowledge import (
    DEFAULT_MAX_DOWNLOAD_BYTES,
    PACK_BUILD_NOT_REQUESTED,
    build_engineering_knowledge_pack_draft,
    default_engineering_knowledge_archive_base_path,
    engineering_knowledge_policy_from_project_config,
    get_engineering_knowledge_pack_detail,
    pack_build_request_from_fields,
    resolve_engineering_knowledge_pack_for_task,
    search_engineering_knowledge_graph,
    search_engineering_knowledge_packs,
    search_engineering_knowledge_retrieval_index,
)
from ...services.engineering_knowledge.archive_paths import build_source_archive_paths
from ...services.engineering_knowledge.archive_store import write_engineering_archive_text
from ...services.engineering_knowledge.runtime_target import upgrade_target_from_request
from ..context import ToolContext


class BuildEngineeringKnowledgePackTool:
    name = "build_engineering_knowledge_pack"
    description = (
        "Create a reviewable Engineering Knowledge Pack draft for exact source/target versions from archived source "
        "evidence and quality gates. Successful builds are submitted for human review, not published."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        # Structured fields only; the user's message is never parsed for a pack build.
        request = pack_build_request_from_fields(
            params,
            source_policy=params.get("source_policy") if isinstance(params.get("source_policy"), dict) else None,
            freshness_policy=params.get("freshness_policy") if isinstance(params.get("freshness_policy"), dict) else None,
            publish_policy=params.get("publish_policy") if isinstance(params.get("publish_policy"), dict) else None,
            review_policy=params.get("review_policy") if isinstance(params.get("review_policy"), dict) else None,
        )
        if not request.is_pack_build_request:
            return {"status": PACK_BUILD_NOT_REQUESTED, "blockers": request.blockers, "pack_id": None}
        workspace_root = Path(context.workspace_root or Path.cwd()).expanduser().resolve()
        archive_base_path = default_engineering_knowledge_archive_base_path()
        source_overrides = _normalize_source_overrides(params.get("source_overrides"))
        max_download_bytes = _bounded_int(
            params.get("max_download_bytes"),
            default=DEFAULT_MAX_DOWNLOAD_BYTES,
            minimum=1,
            maximum=DEFAULT_MAX_DOWNLOAD_BYTES,
        )
        result = await build_engineering_knowledge_pack_draft(
            context.db,
            request=request,
            trigger="agent_tool",
            archive_base_path=archive_base_path,
            source_overrides=source_overrides,
            allowed_roots=[archive_base_path, workspace_root],
            allow_network=_bool_param(params.get("allow_network"), default=True),
            created_by_user_id=context.user_id or None,
            max_download_bytes=max_download_bytes,
        )
        await context.db.flush()
        pack = result.pack
        pack_version = result.pack_version
        return {
            "status": result.build_run.status,
            "build_run_id": result.build_run.id,
            "pack_id": pack.id if pack else None,
            "pack_key": pack.key if pack else None,
            "pack_version_id": pack_version.id if pack_version else None,
            "pack_version": pack_version.version if pack_version else None,
            "archive_root": pack_version.archive_root if pack_version else None,
            "quality_status": pack_version.quality_status if pack_version else "blocked",
            "publish_decision": result.build_run.publish_decision,
            "approval_status": result.build_run.approval_status,
            "blockers": result.blockers,
            "source_plan_count": len((result.build_run.source_plan or {}).get("sources") or []),
            "archived_source_count": result.quality_report.get("archived_source_count", 0),
            "quality_report": result.quality_report,
        }

    def is_read_only(self) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def is_enabled(self) -> bool:
        return True


class SearchEngineeringKnowledgePacksTool:
    name = "engineering_pack_search"
    description = "Search published or review-state Engineering Knowledge Packs by stack, version, topic, and evidence."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        return await search_engineering_knowledge_packs(
            context.db,
            stack_key=str(params.get("stack_key") or "").strip(),
            source_versions=params.get("source_versions") if isinstance(params.get("source_versions"), dict) else None,
            target_versions=params.get("target_versions") if isinstance(params.get("target_versions"), dict) else None,
            topic=str(params.get("topic") or "").strip(),
            artifact=str(params.get("artifact") or "").strip(),
            trust_tier=str(params.get("trust_tier") or "").strip(),
            status=str(params.get("status") or "published").strip(),
            quality_status=str(params.get("quality_status") or "passed").strip(),
            limit=_bounded_int(params.get("limit"), default=10, minimum=1, maximum=50),
        )

    def is_read_only(self) -> bool:
        return True


class RetrieveEngineeringKnowledgePackRecordsTool:
    name = "engineering_pack_retrieve"
    description = (
        "Search active published Engineering Pack retrieval records at pack, item, fact, and source level. "
        "Use this for citation-ready Java/Spring/vendor facts instead of loading a whole Pack."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        return await search_engineering_knowledge_retrieval_index(
            context.db,
            query=str(params.get("query") or "").strip(),
            stack_key=str(params.get("stack_key") or "").strip(),
            source_versions=params.get("source_versions") if isinstance(params.get("source_versions"), dict) else None,
            target_versions=params.get("target_versions") if isinstance(params.get("target_versions"), dict) else None,
            record_kind=str(params.get("record_kind") or "").strip(),
            coverage_area=str(params.get("coverage_area") or "").strip(),
            trust_tier=str(params.get("trust_tier") or "").strip(),
            source_type=str(params.get("source_type") or "").strip(),
            freshness_status=str(params.get("freshness_status") or "").strip(),
            limit=_bounded_int(params.get("limit"), default=10, minimum=1, maximum=50),
        )

    def is_read_only(self) -> bool:
        return True


class SearchEngineeringKnowledgeTool:
    name = "search_engineering_knowledge"
    description = (
        "Search governed Engineering Knowledge Graph facts. Returns compact source-backed guidance filtered by scope, "
        "classification, trust level, and validity. Prefer this for coding standards, fix patterns, vulnerabilities, "
        "pipeline patterns, reviewer expertise, and technology baselines."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await _execute_graph_search(context, params=params)

    def is_read_only(self) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True


class GetRepositoryPatternsTool:
    name = "get_repository_patterns"
    description = "Retrieve governed fix, failure, policy, and technology patterns for a repository or project."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await _execute_graph_search(
            context,
            params=params,
            default_node_types=["fix_pattern", "failure_pattern", "policy_finding", "technology", "runtime"],
        )

    def is_read_only(self) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True


class GetVulnerabilityFixKnowledgeTool:
    name = "get_vulnerability_fix_knowledge"
    description = "Retrieve governed vulnerability and fix-pattern knowledge for a CVE, package, dependency, or stack."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        query = " ".join(
            str(params.get(key) or "").strip()
            for key in ("query", "cve", "package", "dependency", "technology")
            if str(params.get(key) or "").strip()
        )
        return await _execute_graph_search(
            context,
            params={**params, "query": query or params.get("query")},
            default_node_types=["vulnerability", "fix_pattern", "policy_finding", "library"],
        )

    def is_read_only(self) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True


class GetPipelineFailurePatternsTool:
    name = "get_pipeline_failure_patterns"
    description = "Retrieve governed build, CI/CD, and pipeline failure patterns with source evidence."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return await _execute_graph_search(
            context,
            params=params,
            default_node_types=["failure_pattern", "build_pipeline", "pipeline_stage", "fix_pattern"],
        )

    def is_read_only(self) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True


class GetReviewerExpertiseTool:
    name = "get_reviewer_expertise"
    description = "Retrieve governed reviewer, team, and ownership expertise facts for routing code reviews."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        query = " ".join(
            str(params.get(key) or "").strip()
            for key in ("query", "reviewer", "team", "technology")
            if str(params.get(key) or "").strip()
        )
        return await _execute_graph_search(
            context,
            params={**params, "query": query or params.get("query")},
            default_node_types=["reviewer", "team", "repository", "technology"],
        )

    def is_read_only(self) -> bool:
        return True

    def is_concurrency_safe(self) -> bool:
        return True


class GetEngineeringKnowledgePackTool:
    name = "engineering_pack_get"
    description = "Load bounded Engineering Knowledge Pack details, sources, evidence metadata, and retrievable items."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        identifier = str(params.get("pack_version_id") or params.get("pack_key") or "").strip()
        pack_version_id = await _resolve_pack_version_id(
            context.db,
            identifier,
            allow_latest_editable=not identifier,
        )
        return await get_engineering_knowledge_pack_detail(
            context.db,
            pack_key="" if pack_version_id else str(params.get("pack_key") or "").strip(),
            pack_version_id=pack_version_id,
            include_items=_bool_param(params.get("include_items"), default=True),
            include_sources=_bool_param(params.get("include_sources"), default=True),
            max_items=_bounded_int(params.get("max_items"), default=12, minimum=1, maximum=50),
        )

    def is_read_only(self) -> bool:
        return True


class ResolveEngineeringKnowledgePackTool:
    name = "engineering_pack_resolve_for_task"
    description = "Resolve the published quality-passed Engineering Pack context for an exact migration target."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        return await resolve_engineering_knowledge_pack_for_task(
            context.db,
            target=upgrade_target_from_request(params),
            max_items=_bounded_int(params.get("max_items"), default=8, minimum=1, maximum=25),
        )

    def is_read_only(self) -> bool:
        return True


class CreatePackDraftTool:
    name = "pack_draft_create"
    description = (
        "Create or reuse an Engineering Knowledge Pack draft (status=draft). "
        "Call this after you have decided what stack and versions the pack should cover. "
        "Returns pack_key and pack_version_id — use those in subsequent pack_draft_add_item calls."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        pack_name = str(params.get("pack_name") or "").strip()
        stack_key = str(params.get("stack_key") or "").strip()
        description = str(params.get("description") or "").strip()
        source_versions = dict(params.get("source_versions") or {})
        target_versions = dict(params.get("target_versions") or {})
        if not pack_name or not stack_key:
            return {"error": "pack_name and stack_key are required"}

        import re

        def _slug(v: object) -> str:
            text = str(v or "").strip().lower()
            text = re.sub(r"[^a-z0-9._-]+", "-", text)
            return re.sub(r"-{2,}", "-", text).strip("-._") or "unknown"

        parts: list[str] = []
        if "java" in source_versions or "java" in target_versions:
            parts.append(f"java-{_slug(source_versions.get('java'))}-to-{_slug(target_versions.get('java'))}")
        if "spring_boot" in source_versions or "spring_boot" in target_versions:
            parts.append(
                f"spring-boot-{_slug(source_versions.get('spring_boot'))}"
                f"-to-{_slug(target_versions.get('spring_boot'))}"
            )
        if "python" in source_versions or "python" in target_versions:
            parts.append(f"python-{_slug(source_versions.get('python'))}-to-{_slug(target_versions.get('python'))}")
        pack_key = "-".join(parts) if parts else _slug(pack_name)

        existing_pack = (
            await context.db.execute(select(EngineeringKnowledgePack).where(EngineeringKnowledgePack.key == pack_key))
        ).scalar_one_or_none()
        if existing_pack is None:
            pack = EngineeringKnowledgePack(
                id=str(uuid.uuid4()),
                key=pack_key,
                name=pack_name,
                description=description,
                stack_key=stack_key,
                retrieval_policy={"default_context_budget_tokens": 12_000},
                resolution_policy={"ask_user_on_ambiguity": True},
                created_by_user_id=context.user_id or None,
            )
            context.db.add(pack)
            await context.db.flush()
        else:
            pack = existing_pack

        reusable_version = await _find_reusable_draft_version(
            context.db,
            pack_id=pack.id,
            source_versions=source_versions,
            target_versions=target_versions,
        )
        from app.services.engineering_knowledge.pack_seed import seed_pack_sources

        research_sources = [entry for entry in (params.get("research_sources") or []) if isinstance(entry, dict)]

        if reusable_version is not None:
            item_count = (
                await context.db.execute(
                    select(func.count(EngineeringKnowledgePackItem.id)).where(
                        EngineeringKnowledgePackItem.pack_version_id == reusable_version.id
                    )
                )
            ).scalar_one()
            seeded = (
                await seed_pack_sources(context.db, pack_version=reusable_version, sources=research_sources)
                if research_sources
                else []
            )
            return {
                "pack_id": pack.id,
                "pack_key": pack_key,
                "pack_name": pack_name,
                "pack_version_id": reusable_version.id,
                "version": reusable_version.version,
                "status": reusable_version.status,
                "reused_existing_draft": True,
                "item_count": int(item_count or 0),
                "seeded_sources": seeded,
            }

        latest_version = (
            await context.db.execute(
                select(func.max(EngineeringKnowledgePackVersion.version)).where(
                    EngineeringKnowledgePackVersion.pack_id == pack.id
                )
            )
        ).scalar_one()
        version_number = int(latest_version or 0) + 1
        pack_version = EngineeringKnowledgePackVersion(
            id=str(uuid.uuid4()),
            pack_id=pack.id,
            version=version_number,
            status="draft",
            source_versions=source_versions,
            target_versions=target_versions,
            archive_root=f"engineering-knowledge/{pack_key}/v{version_number}",
            quality_status="pending",
            created_by_user_id=context.user_id or None,
        )
        context.db.add(pack_version)
        await context.db.flush()
        seeded = (
            await seed_pack_sources(context.db, pack_version=pack_version, sources=research_sources)
            if research_sources
            else []
        )
        return {
            "pack_id": pack.id,
            "pack_key": pack_key,
            "pack_name": pack_name,
            "pack_version_id": pack_version.id,
            "version": version_number,
            "status": "draft",
            "seeded_sources": seeded,
        }

    def is_read_only(self) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def is_enabled(self) -> bool:
        return True


class AddPackItemTool:
    name = "pack_draft_add_item"
    description = (
        "Add a knowledge item to an existing Engineering Knowledge Pack draft. "
        "The agent writes the content directly from its research — no URL fetching happens here. "
        "Call once per distinct knowledge topic (migration step, breaking change, config key, etc.)."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        pack_version_id = str(params.get("pack_version_id") or "").strip()
        item_key = str(params.get("item_key") or "").strip()
        title = str(params.get("title") or "").strip()
        content = str(params.get("content") or "").strip()
        if not pack_version_id or not item_key or not title or not content:
            return {"error": "pack_version_id, item_key, title, and content are required"}
        content_error = _validate_pack_item_content(content)
        if content_error:
            return {"error": content_error}
        pack_version_id = await _resolve_pack_version_id(context.db, pack_version_id)

        pack_version = (
            await context.db.execute(
                select(EngineeringKnowledgePackVersion).where(EngineeringKnowledgePackVersion.id == pack_version_id)
            )
        ).scalar_one_or_none()
        if pack_version is None:
            return {"error": f"Pack version not found: {pack_version_id}"}
        if pack_version.status not in {"draft", "pending_review"}:
            return {"error": f"Pack version is not editable (status={pack_version.status})"}

        existing = (
            await context.db.execute(
                select(EngineeringKnowledgePackItem).where(
                    EngineeringKnowledgePackItem.pack_version_id == pack_version_id,
                    EngineeringKnowledgePackItem.item_key == item_key,
                )
            )
        ).scalar_one_or_none()

        tags = list(params.get("tags") or [])
        triggers = list(params.get("triggers") or [])
        version_scope = dict(params.get("version_scope") or {})
        retrieval_priority = str(params.get("retrieval_priority") or "normal").strip()
        retrieval_rank = _bounded_int(params.get("retrieval_rank"), default=100, minimum=1, maximum=9999)
        summary = str(params.get("summary") or "").strip()
        source_uri = str(params.get("source_uri") or "").strip()
        trust_tier = str(params.get("trust_tier") or "official").strip()

        item_metadata: dict[str, Any] = {}
        if source_uri:
            item_metadata["source_uri"] = source_uri
        if trust_tier:
            item_metadata["trust_tier"] = trust_tier
        source = None
        if source_uri:
            source = await _upsert_pack_source(
                context.db,
                pack_version_id=pack_version_id,
                item_key=item_key,
                title=title,
                source_uri=source_uri,
                trust_tier=trust_tier,
                content=content,
            )
            item_metadata["evidence"] = [_source_evidence_metadata(source)]

        if existing is not None:
            if source is not None:
                existing.source_id = source.id
            existing.title = title
            existing.content = content
            existing.summary = summary
            existing.tags = tags
            existing.triggers = triggers
            existing.version_scope = version_scope
            existing.retrieval_priority = retrieval_priority
            existing.retrieval_rank = retrieval_rank
            existing.item_metadata = {**existing.item_metadata, **item_metadata}
            await context.db.flush()
            return {"item_id": existing.id, "item_key": item_key, "pack_version_id": pack_version_id, "updated": True}

        item = EngineeringKnowledgePackItem(
            id=str(uuid.uuid4()),
            pack_version_id=pack_version_id,
            source_id=source.id if source is not None else None,
            item_key=item_key,
            title=title,
            content=content,
            summary=summary,
            tags=tags,
            triggers=triggers,
            version_scope=version_scope,
            retrieval_priority=retrieval_priority,
            retrieval_rank=retrieval_rank,
            item_metadata=item_metadata,
        )
        context.db.add(item)
        await context.db.flush()
        return {"item_id": item.id, "item_key": item_key, "pack_version_id": pack_version_id, "updated": False}

    def is_read_only(self) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def is_enabled(self) -> bool:
        return True


class FinalizePackDraftTool:
    name = "pack_draft_finalize"
    description = (
        "Finalize an Engineering Knowledge Pack draft: run quality gates and submit it for human review "
        "(status → pending_review). The pack is NOT published automatically."
    )

    async def execute(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.db is None:
            return {"error": "Database session is required"}
        identifier = str(params.get("pack_version_id") or params.get("pack_key") or "").strip()
        if not identifier:
            return {"error": "pack_version_id or pack_key is required"}
        pack_version_id = await _resolve_pack_version_id(context.db, identifier)

        pack_version = (
            await context.db.execute(
                select(EngineeringKnowledgePackVersion).where(EngineeringKnowledgePackVersion.id == pack_version_id)
            )
        ).scalar_one_or_none()
        if pack_version is None:
            return {"error": f"Pack version not found: {pack_version_id}"}
        if pack_version.status not in {"draft"}:
            return {"error": f"Only draft versions can be finalized (current status={pack_version.status})"}

        items = (
            await context.db.execute(
                select(EngineeringKnowledgePackItem).where(
                    EngineeringKnowledgePackItem.pack_version_id == pack_version_id
                )
            )
        ).scalars().all()
        sources = (
            await context.db.execute(
                select(EngineeringKnowledgePackSource).where(
                    EngineeringKnowledgePackSource.pack_version_id == pack_version_id
                )
            )
        ).scalars().all()
        item_count = len(items)

        blockers: list[str] = []
        minimum_items = _bounded_int(params.get("minimum_items"), default=5, minimum=1, maximum=50)
        if item_count < minimum_items:
            blockers.append(
                f"Engineering Knowledge Pack requires at least {minimum_items} reviewable items; found {item_count}."
            )
        placeholder_items = [
            item.item_key for item in items if _validate_pack_item_content(str(item.content or ""))
        ]
        if placeholder_items:
            blockers.append(
                "Knowledge items must contain substantive source-backed content, not placeholders: "
                + ", ".join(sorted(placeholder_items)[:10])
            )
        missing_source_items = [
            item.item_key for item in items if not str(dict(item.item_metadata or {}).get("source_uri") or "").strip()
        ]
        if missing_source_items:
            blockers.append(
                "Knowledge items must include source_uri evidence: "
                + ", ".join(sorted(missing_source_items)[:10])
            )
        missing_trigger_items = [item.item_key for item in items if not list(item.triggers or [])]
        if missing_trigger_items:
            blockers.append(
                "Knowledge items must include retrieval triggers: "
                + ", ".join(sorted(missing_trigger_items)[:10])
            )
        missing_version_scope_items = [item.item_key for item in items if not dict(item.version_scope or {})]
        if missing_version_scope_items:
            blockers.append(
                "Knowledge items must include version_scope: "
                + ", ".join(sorted(missing_version_scope_items)[:10])
            )
        missing_evidence_fact_items = [
            item.item_key for item in items if not list(dict(item.item_metadata or {}).get("evidence_fact_ids") or [])
        ]
        if missing_evidence_fact_items:
            blockers.append(
                "Knowledge items must link to Evidence Ledger facts: "
                + ", ".join(sorted(missing_evidence_fact_items)[:10])
            )
        source_by_id = {source.id: source for source in sources}
        unarchived_sources = [
            source.source_key
            for source in sources
            if not (source.checksum and source.raw_archive_path and source.parsed_archive_path and source.evidence_archive_path)
        ]
        if unarchived_sources:
            blockers.append(
                "Sources must be locally archived with raw, parsed, and evidence artifacts: "
                + ", ".join(sorted(unarchived_sources)[:10])
            )
        non_canonical_sources = [
            source.source_key for source in sources if urlsplit(str(source.source_uri or "")).scheme not in {"http", "https"}
        ]
        if non_canonical_sources:
            blockers.append(
                "Sources must use canonical HTTP(S) reference URLs, not tool-internal URIs: "
                + ", ".join(sorted(non_canonical_sources)[:10])
            )
        unaudited_sources = [
            source.source_key
            for source in sources
            if str(dict(source.source_metadata or {}).get("source_audit", {}).get("status") or "")
            not in {"accepted", "limited"}
        ]
        if unaudited_sources:
            blockers.append(
                "Sources must pass source audit before finalizing: "
                + ", ".join(sorted(unaudited_sources)[:10])
            )
        items_without_archived_source = [
            item.item_key
            for item in items
            if not item.source_id or item.source_id not in source_by_id or item.source_id in {source.id for source in sources if source.source_key in unarchived_sources}
        ]
        if items_without_archived_source:
            blockers.append(
                "Knowledge items must link to an archived source row: "
                + ", ".join(sorted(items_without_archived_source)[:10])
            )

        notes = str(params.get("notes") or "").strip()
        quality_status = "passed" if not blockers else "blocked"

        quality_report = {
            "item_count": item_count,
            "minimum_item_count": minimum_items,
            "source_count": len(sources),
            "archived_source_count": len(sources) - len(unarchived_sources),
            "item_evidence_complete_count": item_count - len(missing_source_items),
            "quality_status": quality_status,
            "blockers": blockers,
            "finalized_by": "agent",
        }
        pack_version.status = "pending_review" if not blockers else "draft"
        pack_version.quality_status = quality_status
        pack_version.quality_report = quality_report
        if notes:
            pack_version.notes = notes
        await context.db.flush()

        return {
            "pack_version_id": pack_version_id,
            "status": pack_version.status,
            "quality_status": quality_status,
            "item_count": int(item_count or 0),
            "blockers": blockers,
            "message": (
                "Draft submitted for review — a human must approve before it is published."
                if not blockers
                else "Draft has blockers and was not submitted for review."
            ),
        }

    def is_read_only(self) -> bool:
        return False

    def is_concurrency_safe(self) -> bool:
        return False

    def is_enabled(self) -> bool:
        return True


def _normalize_source_overrides(value: Any) -> dict[str, Path]:
    if isinstance(value, dict):
        return {str(key): Path(str(path)) for key, path in value.items() if str(key).strip() and str(path).strip()}
    if not isinstance(value, list):
        return {}
    overrides: dict[str, Path] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        source_key = str(item.get("source_key") or item.get("key") or "").strip()
        path = str(item.get("path") or item.get("file_path") or "").strip()
        if source_key and path:
            overrides[source_key] = Path(path)
    return overrides


async def _resolve_pack_version_id(db, identifier: str, *, allow_latest_editable: bool = False) -> str:
    """Accept pack version ids, pack ids, pack keys, and simple target-version aliases."""
    if not identifier:
        if allow_latest_editable:
            latest_version = await _latest_editable_pack_version(db)
            return latest_version.id if latest_version is not None else ""
        return ""
    existing_version = (
        await db.execute(select(EngineeringKnowledgePackVersion.id).where(EngineeringKnowledgePackVersion.id == identifier))
    ).scalar_one_or_none()
    if existing_version:
        return str(existing_version)
    pack = (
        await db.execute(
            select(EngineeringKnowledgePack).where(
                (EngineeringKnowledgePack.id == identifier) | (EngineeringKnowledgePack.key == identifier)
            )
        )
    ).scalar_one_or_none()
    if pack is None:
        aliased_version = await _version_for_simple_target_alias(db, identifier)
        return aliased_version.id if aliased_version is not None else identifier
    resolved = await _latest_pack_version(db, pack.id)
    return resolved.id if resolved is not None else identifier


async def _latest_pack_version(db, pack_id: str) -> EngineeringKnowledgePackVersion | None:
    return (
        await db.execute(
            select(EngineeringKnowledgePackVersion)
            .where(EngineeringKnowledgePackVersion.pack_id == pack_id)
            .order_by(
                EngineeringKnowledgePackVersion.updated_at.desc(),
                EngineeringKnowledgePackVersion.version.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _latest_editable_pack_version(db) -> EngineeringKnowledgePackVersion | None:
    return (
        await db.execute(
            select(EngineeringKnowledgePackVersion)
            .where(
                EngineeringKnowledgePackVersion.status.in_(["draft", "pending_review"]),
            )
            .order_by(
                EngineeringKnowledgePackVersion.updated_at.desc(),
                EngineeringKnowledgePackVersion.version.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _version_for_simple_target_alias(db, identifier: str) -> EngineeringKnowledgePackVersion | None:
    match = re.fullmatch(r"(?P<stack>[a-z][a-z0-9_-]*)-(?P<target>[0-9][a-z0-9._-]*)", identifier.lower())
    if match is None:
        return None
    stack_key = match.group("stack")
    target_version = match.group("target")
    versions = (
        await db.execute(
            select(EngineeringKnowledgePackVersion)
            .join(EngineeringKnowledgePack, EngineeringKnowledgePack.id == EngineeringKnowledgePackVersion.pack_id)
            .where(
                EngineeringKnowledgePack.stack_key.in_([stack_key, f"{stack_key}-spring"]),
                EngineeringKnowledgePackVersion.status.in_(["draft", "pending_review", "published"]),
            )
            .order_by(
                EngineeringKnowledgePackVersion.status.asc(),
                EngineeringKnowledgePackVersion.updated_at.desc(),
                EngineeringKnowledgePackVersion.version.desc(),
            )
            .limit(50)
        )
    ).scalars().all()
    for version in versions:
        if str(dict(version.target_versions or {}).get(stack_key) or "").lower() == target_version:
            return version
    return None


async def _find_reusable_draft_version(
    db,
    *,
    pack_id: str,
    source_versions: dict[str, Any],
    target_versions: dict[str, Any],
) -> EngineeringKnowledgePackVersion | None:
    versions = (
        await db.execute(
            select(EngineeringKnowledgePackVersion)
            .where(
                EngineeringKnowledgePackVersion.pack_id == pack_id,
                EngineeringKnowledgePackVersion.status.in_(["draft", "pending_review"]),
                EngineeringKnowledgePackVersion.quality_status != "blocked",
            )
            .order_by(
                EngineeringKnowledgePackVersion.updated_at.desc(),
                EngineeringKnowledgePackVersion.version.desc(),
            )
        )
    ).scalars().all()
    for version in versions:
        if _version_maps_equal(version.source_versions, source_versions) and _version_maps_equal(
            version.target_versions,
            target_versions,
        ):
            return version
    return None


def _version_maps_equal(left: Any, right: dict[str, Any]) -> bool:
    left_map = {str(key): str(value) for key, value in dict(left or {}).items() if str(value).strip()}
    right_map = {str(key): str(value) for key, value in dict(right or {}).items() if str(value).strip()}
    return left_map == right_map


async def _execute_graph_search(
    context: ToolContext,
    *,
    params: dict[str, Any],
    default_node_types: list[str] | None = None,
) -> dict[str, Any]:
    if context.db is None:
        return {"error": "Database session is required"}
    policy = engineering_knowledge_policy_from_project_config(context.project_config)
    node_types = _list_param(params.get("node_types") or params.get("node_type"))
    allowed_classifications = _classification_param(params.get("classification"), policy["allowed_classifications"])
    include_silver = _bool_param(params.get("include_silver"), default=False) and bool(policy["include_silver"])
    repository_id = str(
        params.get("repository_id")
        or params.get("code_repository_id")
        or (context.project_config or {}).get("repository_id")
        or ""
    ).strip()
    return await search_engineering_knowledge_graph(
        context.db,
        query=str(params.get("query") or "").strip(),
        node_types=node_types or default_node_types,
        repository_id=repository_id or None,
        project_ids=[str(item) for item in (context.project_ids or []) if str(item).strip()],
        allowed_classifications=allowed_classifications,
        include_silver=include_silver,
        limit=_bounded_int(params.get("limit"), default=10, minimum=1, maximum=25),
    )


def _list_param(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _classification_param(value: Any, policy_classifications: list[str]) -> list[str]:
    requested = _list_param(value)
    if not requested:
        return policy_classifications
    allowed = {item.strip().lower() for item in policy_classifications}
    return [item for item in requested if item.strip().lower() in allowed]


def _validate_pack_item_content(content: str) -> str:
    normalized = " ".join(str(content or "").strip().lower().split())
    if normalized in {"todo", "tbd", "placeholder", "n/a", "na"}:
        return "content must be substantive; placeholder values like TODO are not allowed"
    if len(str(content or "").strip()) < 120:
        return "content must be at least 120 characters of source-backed guidance"
    return ""


async def _upsert_pack_source(
    db,
    *,
    pack_version_id: str,
    item_key: str,
    title: str,
    source_uri: str,
    trust_tier: str,
    content: str,
) -> EngineeringKnowledgePackSource:
    pack_version = await db.get(EngineeringKnowledgePackVersion, pack_version_id)
    pack = await db.get(EngineeringKnowledgePack, pack_version.pack_id) if pack_version is not None else None
    if pack_version is None or pack is None:
        raise ValueError("Pack version is required to archive source evidence")
    source_audit = audit_engineering_knowledge_source(
        EngineeringKnowledgeSourceSpec(
            source_key=_source_key(item_key=item_key, source_uri=source_uri),
            title=title,
            source_uri=source_uri,
            source_type=_source_type(source_uri),
            trust_tier=trust_tier or "official",
            metadata={"target_versions": dict(pack_version.target_versions or {})},
        ),
        target_versions=pack_version.target_versions or {},
    )
    source_key = _source_key(item_key=item_key, source_uri=source_uri)
    archive = _archive_pack_item_source(
        pack_key=pack.key,
        pack_version=pack_version.version,
        source_key=source_key,
        title=title,
        source_uri=source_uri,
        source_type=_source_type(source_uri),
        trust_tier=trust_tier or "official",
        content=content,
    )
    existing = (
        await db.execute(
            select(EngineeringKnowledgePackSource).where(
                EngineeringKnowledgePackSource.pack_version_id == pack_version_id,
                EngineeringKnowledgePackSource.source_key == source_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.title = title
        existing.source_uri = source_uri
        existing.trust_tier = trust_tier or "official"
        existing.checksum = archive["checksum"]
        existing.fetch_status = "fetched"
        existing.freshness_status = "fresh"
        existing.raw_archive_path = archive["raw_archive_path"]
        existing.parsed_archive_path = archive["parsed_archive_path"]
        existing.evidence_archive_path = archive["evidence_archive_path"]
        existing.source_metadata = {
            **dict(existing.source_metadata or {}),
            "source_uri": source_uri,
            "source_audit": source_audit.to_metadata(),
        }
        await db.flush()
        return existing

    source = EngineeringKnowledgePackSource(
        id=str(uuid.uuid4()),
        pack_version_id=pack_version_id,
        source_key=source_key,
        title=title,
        source_uri=source_uri,
        source_type=_source_type(source_uri),
        trust_tier=trust_tier or "official",
        checksum=archive["checksum"],
        fetch_status="fetched",
        freshness_status="fresh",
        raw_archive_path=archive["raw_archive_path"],
        parsed_archive_path=archive["parsed_archive_path"],
        evidence_archive_path=archive["evidence_archive_path"],
        source_metadata={"source_uri": source_uri, "source_audit": source_audit.to_metadata()},
    )
    db.add(source)
    await db.flush()
    return source


def _archive_pack_item_source(
    *,
    pack_key: str,
    pack_version: int,
    source_key: str,
    title: str,
    source_uri: str,
    source_type: str,
    trust_tier: str,
    content: str,
) -> dict[str, str]:
    paths = build_source_archive_paths(pack_slug=pack_key, pack_version=pack_version, source_key=source_key)
    raw_archive_path = str(Path(paths.raw) / "content.md")
    parsed_archive_path = str(Path(paths.parsed) / "content.md")
    evidence_archive_path = str(Path(paths.evidence) / "evidence.json")
    write_engineering_archive_text(raw_archive_path, content, content_type="text/markdown")
    write_engineering_archive_text(parsed_archive_path, content, content_type="text/markdown")
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    evidence = {
        "source_key": source_key,
        "title": title,
        "source_uri": source_uri,
        "source_type": source_type,
        "trust_tier": trust_tier,
        "checksum": checksum,
        "fetch_status": "fetched",
        "freshness_status": "fresh",
        "raw_archive_path": raw_archive_path,
        "parsed_archive_path": parsed_archive_path,
    }
    write_engineering_archive_text(
        evidence_archive_path,
        json.dumps(evidence, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
    return {
        "checksum": checksum,
        "raw_archive_path": raw_archive_path,
        "parsed_archive_path": parsed_archive_path,
        "evidence_archive_path": evidence_archive_path,
    }


def _source_key(*, item_key: str, source_uri: str) -> str:
    raw = source_uri.rsplit("/", 1)[-1] or source_uri
    slug = re.sub(r"[^a-z0-9._-]+", "-", raw.lower()).strip("-._")
    slug = re.sub(r"-{2,}", "-", slug)[:80] or "source"
    return f"{item_key}-{slug}"


def _source_type(source_uri: str) -> str:
    if source_uri.startswith("context7://"):
        return "context7"
    if source_uri.startswith("http://") or source_uri.startswith("https://"):
        return "documentation"
    if source_uri.startswith("mcp://"):
        return "mcp"
    return "external"


def _source_evidence_metadata(source: EngineeringKnowledgePackSource) -> dict[str, Any]:
    source_metadata = dict(source.source_metadata or {})
    return {
        "source_id": source.id,
        "source_key": source.source_key,
        "title": source.title,
        "source_uri": source.source_uri,
        "source_type": source.source_type,
        "trust_tier": source.trust_tier,
        "checksum": source.checksum,
        "raw_archive_path": source.raw_archive_path,
        "parsed_archive_path": source.parsed_archive_path,
        "evidence_archive_path": source.evidence_archive_path,
        "freshness_status": source.freshness_status,
        "fetch_status": source.fetch_status,
        "source_audit": dict(source_metadata.get("source_audit") or {}),
    }


def _bool_param(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
