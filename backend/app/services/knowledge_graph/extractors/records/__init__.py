"""Deterministic extractors for semi-structured records (people, tickets, pages)."""

from __future__ import annotations

from .documents import ingest_document_record
from .people import _CONTRIBUTION_EDGE_BY_ROLE, ingest_person_from_source, ingest_person_identity
from .releases import ingest_release_record
from .repositories import _SERVICE_ACCOUNT_MARKERS, _is_service_account, ingest_repository_record
from .tickets import ingest_ticket_record

__all__ = [
    "_CONTRIBUTION_EDGE_BY_ROLE",
    "_SERVICE_ACCOUNT_MARKERS",
    "_is_service_account",
    "ingest_document_record",
    "ingest_person_from_source",
    "ingest_person_identity",
    "ingest_release_record",
    "ingest_repository_record",
    "ingest_ticket_record",
]
