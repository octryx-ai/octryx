"""The operations layer of one record revision."""

from __future__ import annotations

from .facts import Extraction
from .ops_records import extract_inventory, extract_jira, extract_servicenow
from .sources import Candidate, current_revisions, load_span_inputs
from .texts import SpanIndex, read_revision_text
from .tickets import jira_pattern, jira_project_keys

EXTRACTOR = "ops-rules"


async def select_operations(context) -> list[Candidate]:
    profile = context.profile
    return await current_revisions(
        context.db, context.project_id,
        source_key_prefixes=tuple(f"{kind}." for kind in profile.ops_connector_kinds),
    )


async def extract_operations(context, candidate: Candidate) -> tuple[str, Extraction]:
    if "jira" not in context.memo:
        context.memo["jira"] = jira_pattern(await jira_project_keys(context.db, context.project_id))
    index = SpanIndex.of(await load_span_inputs(context.db, context.project_id, candidate.revision_id))
    text = await read_revision_text(context, candidate)
    kind = candidate.source_key.split(".", 1)[0]
    if kind == "servicenow":
        return EXTRACTOR, extract_servicenow(text, index.at_offset, context.profile, context.memo["jira"])
    if kind == "jira":
        return EXTRACTOR, extract_jira(text, index.at_offset, context.profile, context.memo["jira"])
    if kind == "kubernetes":
        return EXTRACTOR, extract_inventory(text, index.at_offset, context.profile)
    extraction = Extraction()
    extraction.warn("record_kind_unknown")
    return EXTRACTOR, extraction


__all__ = ["EXTRACTOR", "extract_operations", "select_operations"]
