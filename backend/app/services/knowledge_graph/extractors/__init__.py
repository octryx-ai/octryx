"""Graph extractors: source-type adapters that map Bronze snapshots into the graph."""

from .code_graph import ingest_code_graph_record
from .common import slugify
from .pack_item import ingest_pack_item_record
from .prose import build_extraction_prompt, extract_graph_from_text
from .records import (
    ingest_document_record,
    ingest_person_from_source,
    ingest_person_identity,
    ingest_release_record,
    ingest_repository_record,
    ingest_ticket_record,
)
from .repo_manifest import ingest_repository_manifest
from .structured import ingest_aws_topology, ingest_database_schema, ingest_terraform, ingest_topology_snapshot
from .structured_code import ingest_code_structure

__all__ = [
    "build_extraction_prompt",
    "extract_graph_from_text",
    "ingest_aws_topology",
    "ingest_code_graph_record",
    "ingest_code_structure",
    "ingest_database_schema",
    "ingest_document_record",
    "ingest_pack_item_record",
    "ingest_person_from_source",
    "ingest_person_identity",
    "ingest_release_record",
    "ingest_repository_manifest",
    "ingest_repository_record",
    "ingest_terraform",
    "ingest_ticket_record",
    "ingest_topology_snapshot",
    "slugify",
]
