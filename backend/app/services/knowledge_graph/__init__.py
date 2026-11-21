"""Knowledge graph (tier 2): entities, relations, aliases, claims + retrieval."""

from .communities import build_communities, detect_communities, global_search, search_communities
from .extractors import (
    build_extraction_prompt,
    extract_graph_from_text,
    ingest_aws_topology,
    ingest_code_structure,
    ingest_database_schema,
    ingest_person_identity,
    ingest_terraform,
    ingest_ticket_record,
    slugify,
)
from .identity import decide_merge_proposal, merge_nodes, propose_identity_merges
from .llm_runtime import (
    ROLE_EXTRACT,
    ROLE_KEYWORDS,
    ROLE_SUMMARIZE,
    KnowledgeLLMRuntimeFailedError,
    KnowledgeLLMUnavailableError,
    build_generate_fn,
)
from .ontology import (
    DEFAULT_ENTITY_TYPES,
    DEFAULT_RELATION_TYPES,
    resolve_active_ontology,
    resolve_ontology,
)
from .query_keywords import QueryKeywords, extract_query_keywords
from .retrieval import search_graph_edges, search_graph_nodes
from .store import (
    add_claim,
    get_claims_for_node,
    get_neighbors,
    merge_descriptions,
    normalize_alias,
    replace_claims_of_type,
    resolve_node_by_alias,
    resummarize_node_description,
    upsert_edge,
    upsert_node,
)

__all__ = [
    "DEFAULT_ENTITY_TYPES",
    "DEFAULT_RELATION_TYPES",
    "KnowledgeLLMRuntimeFailedError",
    "KnowledgeLLMUnavailableError",
    "QueryKeywords",
    "ROLE_EXTRACT",
    "ROLE_KEYWORDS",
    "ROLE_SUMMARIZE",
    "add_claim",
    "replace_claims_of_type",
    "build_communities",
    "build_extraction_prompt",
    "build_generate_fn",
    "decide_merge_proposal",
    "detect_communities",
    "extract_query_keywords",
    "global_search",
    "extract_graph_from_text",
    "get_claims_for_node",
    "get_neighbors",
    "ingest_aws_topology",
    "ingest_code_structure",
    "ingest_database_schema",
    "ingest_person_identity",
    "ingest_terraform",
    "ingest_ticket_record",
    "merge_descriptions",
    "merge_nodes",
    "normalize_alias",
    "propose_identity_merges",
    "resolve_active_ontology",
    "resolve_node_by_alias",
    "resolve_ontology",
    "resummarize_node_description",
    "search_communities",
    "search_graph_edges",
    "search_graph_nodes",
    "slugify",
    "upsert_edge",
    "upsert_node",
]
