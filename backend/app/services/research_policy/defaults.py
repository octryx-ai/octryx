from __future__ import annotations

import copy
from typing import Any

_SCIENTIFIC_LITERATURE_DOMAINS = [
    "semanticscholar.org",
    "openalex.org",
    "crossref.org",
    "doi.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
    "ieeexplore.ieee.org",
    "dl.acm.org",
    "sciencedirect.com",
    "link.springer.com",
    "nature.com",
    "science.org",
    "wiley.com",
    "tandfonline.com",
    "sagepub.com",
    "jstor.org",
    "plos.org",
    "frontiersin.org",
    "bmj.com",
    "nejm.org",
    "thelancet.com",
]


def _base_policy_spec() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_policy": {
            "modalities": ["html", "pdf", "office", "text"],
            "prefer_primary_sources": True,
            "prefer_pdf_when_available": True,
            "allow_secondary_sources": True,
            "reject_low_signal_sources": True,
            "max_download_bytes": 52_428_800,
            "literature_policy": {
                "enabled": False,
                "mode": "auto",
                "require_published_sources": False,
                "require_peer_reviewed_sources": False,
                "exclude_preprints": True,
                "restrict_to_preferred_domains": False,
                "preferred_domains": _SCIENTIFIC_LITERATURE_DOMAINS,
                "preferred_databases": ["Semantic Scholar", "OpenAlex", "Crossref", "PubMed"],
            },
        },
        "delegation_policy": {
            "enabled": True,
            "max_child_agents": 3,
            "child_runtime_timeout_seconds": 90,
            "child_group_timeout_seconds": 900,
            "child_result_acceptance": {
                "require_source_urls": True,
                "require_downloaded_evidence": True,
                "min_sources_per_child": 1,
            },
        },
        "plan_policy": {
            "require_outline_before_final": True,
            "required_axes": [
                "executive_summary",
                "benefits",
                "risks",
                "use_cases",
                "recommendation",
                "references",
            ],
            "min_sections": 6,
        },
        "evidence_archive": {
            "enabled": True,
            "workspace_folder": "research",
            "preserve_raw_sources": True,
            "preserve_parsed_text": True,
            "write_source_manifests": True,
            "write_bundle_manifest": True,
            "capture_response_headers": True,
        },
        "quality_gates": {
            "require_source_ids_in_sections": True,
            "require_references_section": True,
            "block_final_if_evidence_below_minimum": True,
        },
    }


def _standard_research_policy_spec() -> dict[str, Any]:
    spec = _base_policy_spec()
    spec["profile_key"] = "standard-research-document"
    spec["research_strategy"] = {
        "mode": "research",
        "min_source_count": 6,
        "target_source_count": 10,
        "max_source_count": 24,
        "max_search_rounds": 4,
        "live_crawl": True,
    }
    spec["output_policy"] = {
        "target_artifact": "docx",
        "target_pages": {"min": 4, "target": 8, "max": 12},
        "citation_style": "ieee",
        "require_references_section": True,
    }
    spec["quality_gates"].update(
        {
            "min_cited_sources": 6,
            "min_substantive_sections": 6,
            "min_pdf_or_office_sources": 1,
            "min_document_words": 2200,
            "max_placeholder_phrases": 0,
            "max_llm_requests": 12,
        }
    )
    return spec


def _deep_research_policy_spec() -> dict[str, Any]:
    spec = _base_policy_spec()
    spec["profile_key"] = "deep-research-document"
    spec["research_strategy"] = {
        "mode": "deep",
        "min_source_count": 20,
        "target_source_count": 40,
        "max_source_count": 120,
        "max_search_rounds": 10,
        "live_crawl": True,
    }
    spec["source_policy"].update(
        {
            "required_source_mix": {
                "primary_or_official": 10,
                "pdf_or_office": 3,
            },
        }
    )
    spec["delegation_policy"].update(
        {
            "max_child_agents": 5,
            "child_runtime_timeout_seconds": 180,
            "child_group_timeout_seconds": 7200,
        }
    )
    spec["delegation_policy"]["child_result_acceptance"].update(
        {
            "min_sources_per_child": 3,
            "require_source_quality_notes": True,
        }
    )
    spec["plan_policy"].update(
        {
            "required_axes": [
                "executive_summary",
                "research_method",
                "market_context",
                "architecture",
                "integration_patterns",
                "benefits",
                "risks",
                "security",
                "implementation_plan",
                "recommendations",
                "references",
            ],
            "min_sections": 10,
        }
    )
    spec["output_policy"] = {
        "target_artifact": "docx",
        "target_pages": {"min": 12, "target": 20, "max": 30},
        "citation_style": "ieee",
        "require_references_section": True,
    }
    spec["quality_gates"].update(
        {
            "min_cited_sources": 20,
            "min_substantive_sections": 10,
            "min_pdf_or_office_sources": 3,
            "min_document_words": 6000,
            "max_placeholder_phrases": 0,
            "max_llm_requests": 20,
            "require_pdf_attempts_when_available": True,
        }
    )
    return spec


def _scientific_literature_policy_spec() -> dict[str, Any]:
    spec = _base_policy_spec()
    spec["profile_key"] = "scientific-literature-review"
    spec["research_strategy"] = {
        "mode": "literature",
        "min_source_count": 12,
        "target_source_count": 30,
        "max_source_count": 80,
        "max_search_rounds": 10,
        "live_crawl": True,
    }
    spec["source_policy"].update(
        {
            "research_mode": "literature",
            "required_source_mix": {
                "scholarly_or_peer_reviewed": 12,
                "pdf_or_office": 4,
            },
            "literature_policy": {
                "enabled": True,
                "mode": "literature",
                "require_published_sources": True,
                "require_peer_reviewed_sources": True,
                "exclude_preprints": True,
                "restrict_to_preferred_domains": True,
                "preferred_domains": _SCIENTIFIC_LITERATURE_DOMAINS,
                "preferred_databases": ["Semantic Scholar", "OpenAlex", "Crossref", "PubMed"],
                "allowed_publication_types": [
                    "journal-article",
                    "conference-paper",
                    "review",
                    "systematic-review",
                    "meta-analysis",
                ],
                "excluded_publication_types": ["preprint", "working-paper", "draft", "preview"],
            },
        }
    )
    spec["delegation_policy"].update(
        {
            "max_child_agents": 5,
            "child_runtime_timeout_seconds": 180,
            "child_group_timeout_seconds": 7200,
        }
    )
    spec["delegation_policy"]["child_result_acceptance"].update(
        {
            "min_sources_per_child": 3,
            "require_source_quality_notes": True,
        }
    )
    spec["plan_policy"].update(
        {
            "required_axes": [
                "abstract",
                "research_method",
                "search_strategy",
                "evidence_synthesis",
                "key_findings",
                "limitations",
                "research_gaps",
                "recommendations",
                "references",
            ],
            "min_sections": 9,
        }
    )
    spec["output_policy"] = {
        "target_artifact": "docx",
        "target_pages": {"min": 10, "target": 18, "max": 28},
        "citation_style": "apa",
        "require_references_section": True,
    }
    spec["quality_gates"].update(
        {
            "min_cited_sources": 12,
            "min_substantive_sections": 8,
            "min_pdf_or_office_sources": 3,
            "min_document_words": 5000,
            "max_placeholder_phrases": 0,
            "max_llm_requests": 20,
            "require_pdf_attempts_when_available": True,
        }
    )
    return spec


DEFAULT_RESEARCH_POLICY_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "key": "standard-research-document",
        "name": "Standard Research Document",
        "description": "Balanced cited research report profile with preserved evidence artifacts.",
        "version": 1,
        "status": "published",
        "spec": _standard_research_policy_spec(),
    },
    {
        "key": "deep-research-document",
        "name": "Deep Research Document",
        "description": "High-depth research report profile for long-form analysis and broad evidence collection.",
        "version": 1,
        "status": "published",
        "spec": _deep_research_policy_spec(),
    },
    {
        "key": "scientific-literature-review",
        "name": "Scientific Literature Review",
        "description": "Published peer-reviewed literature review profile with strict scholarly source filtering.",
        "version": 1,
        "status": "published",
        "spec": _scientific_literature_policy_spec(),
    },
)


def default_research_policy_profiles() -> list[dict[str, Any]]:
    return copy.deepcopy(list(DEFAULT_RESEARCH_POLICY_PROFILES))


__all__ = ["DEFAULT_RESEARCH_POLICY_PROFILES", "default_research_policy_profiles"]
