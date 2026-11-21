"""Document ingestion package exports."""

from .common import REPO_ROOT
from .parse import ParsedDocument
from .service import ingest_document_source, query_document_knowledge

__all__ = [
    "ParsedDocument",
    "REPO_ROOT",
    "ingest_document_source",
    "query_document_knowledge",
]
