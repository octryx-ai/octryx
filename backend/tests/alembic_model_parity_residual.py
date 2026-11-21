"""The exact ``compare_metadata`` output a fresh ``alembic upgrade head`` may still show against the models.

The schema has one revision generated from the models, so the models and the database agree. What remains are the
PostgreSQL-only Knowledge tables that revision creates by hand and no model declares (the evidence index and the
temporal graph). The parity tests fail on any new drift and on any listed drift that no longer occurs.
"""

from __future__ import annotations

DriftKey = tuple[str, ...]

NEVER_MODELLED_TABLE = "PostgreSQL-only table the initial revision creates by hand, no model declares it"
NEVER_MODELLED_INDEX = "index of such a table"
SQLITE_DIALECT_DIFFERENCE = "accepted: SQLite dialect difference"


def _classified(label: str, kind: str, *entries: tuple[str, ...]) -> dict[DriftKey, str]:
    return {(kind, *entry): label for entry in entries}


RESIDUAL_DRIFT_BOTH_DIALECTS: dict[DriftKey, str] = {}

RESIDUAL_DRIFT_SQLITE_ONLY: dict[DriftKey, str] = {}

RESIDUAL_DRIFT_POSTGRESQL_ONLY: dict[DriftKey, str] = {
    **_classified(
        NEVER_MODELLED_TABLE,
        "remove_table",
        ("kg_node",),
        ("kg_edge",),
        ("knowledge_evidence_index",),
        ("knowledge_evidence_vectors",),
    ),
    **_classified(
        NEVER_MODELLED_INDEX,
        "remove_index",
        ("kg_node", "ix_kg_node_group"),
        ("kg_edge", "ix_kg_edge_group"),
        ("kg_edge", "ix_kg_edge_source"),
        ("kg_edge", "ix_kg_edge_target"),
        ("kg_edge", "ix_kg_edge_episodes"),
        ("kg_edge", "ix_kg_edge_fact_tsv"),
        ("knowledge_evidence_index", "ix_knowledge_evidence_index_body_tsv"),
        ("knowledge_evidence_index", "ix_knowledge_evidence_index_acl_keys"),
        ("knowledge_evidence_index", "ix_knowledge_evidence_index_products"),
        ("knowledge_evidence_index", "ix_knowledge_evidence_index_revision"),
    ),
}

# The residual size per dialect; it may only shrink.
RESIDUAL_BASELINE = {"sqlite": 0, "postgresql": 14}


def expected_residual(dialect_name: str) -> dict[DriftKey, str]:
    dialect_only = {"sqlite": RESIDUAL_DRIFT_SQLITE_ONLY, "postgresql": RESIDUAL_DRIFT_POSTGRESQL_ONLY}
    return {**RESIDUAL_DRIFT_BOTH_DIALECTS, **dialect_only[dialect_name]}
