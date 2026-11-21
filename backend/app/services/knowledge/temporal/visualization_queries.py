"""Fixed, bounded graph reads for the current Workspace knowledge explorer."""

from __future__ import annotations

from sqlalchemy import select

from ....models.project.knowledge_evidence import (
    REVISION_STATE_PROJECTED,
    KnowledgeEvidenceSource,
    KnowledgeSourceRevision,
)
from ....models.project.knowledge_temporal import KnowledgeGraphEpisode
from ..access.source_acl import visible_source

MAX_EPISODES = 1000
MAX_CANDIDATES = 600
MAX_NODES = 150
MAX_EDGES = 300
QUERY_SECONDS = 8

FACTS_QUERY = (
    "MATCH (a:Entity)-[e:RELATES_TO]->(b:Entity) "
    "WHERE size([episode IN e.episodes WHERE episode IN $episodes]) > 0 "
    "AND ($focus = '' OR a.uuid = $focus OR b.uuid = $focus) "
    "AND ($query = '' OR toLower(a.name) CONTAINS $query "
    "OR toLower(b.name) CONTAINS $query OR toLower(e.fact) CONTAINS $query) "
    "RETURN e.uuid AS uuid, e.name AS relation, e.fact AS fact, e.episodes AS episodes, "
    "e.created_at AS created_at, a.name AS source, b.name AS target, "
    "a.uuid AS source_uuid, b.uuid AS target_uuid ORDER BY e.uuid LIMIT $limit"
)
# The totals of the same visible window (every fact whose episode the reader may see), not of the shown page.
COUNT_QUERY = (
    "MATCH (a:Entity)-[e:RELATES_TO]->(b:Entity) "
    "WHERE size([episode IN e.episodes WHERE episode IN $episodes]) > 0 "
    "UNWIND [a.uuid, b.uuid] AS node "
    "RETURN count(DISTINCT node) AS nodes, count(DISTINCT e.uuid) AS edges"
)


async def visible_episodes(db, authorized):
    """Bound the candidate window after SQL source ACL and current-revision checks."""
    rows = (await db.execute(
        select(KnowledgeGraphEpisode)
        .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == KnowledgeGraphEpisode.revision_id)
        .join(KnowledgeEvidenceSource, KnowledgeEvidenceSource.id == KnowledgeSourceRevision.source_id)
        .where(
            KnowledgeGraphEpisode.project_id == authorized.project_id,
            KnowledgeSourceRevision.project_id == authorized.project_id,
            KnowledgeSourceRevision.state == REVISION_STATE_PROJECTED,
            KnowledgeEvidenceSource.project_id == authorized.project_id,
            visible_source(authorized.project_id, KnowledgeEvidenceSource.source_key, authorized.principal_keys),
        )
        .order_by(KnowledgeGraphEpisode.extracted_at.desc(), KnowledgeGraphEpisode.episode_uuid)
        .limit(MAX_EPISODES + 1)
    )).scalars().all()
    return rows[:MAX_EPISODES], len(rows) > MAX_EPISODES
