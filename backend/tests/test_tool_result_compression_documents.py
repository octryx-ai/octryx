from app.services.tool_result_compression.registry import get_strategy_handler


def test_document_ingest_compression_preserves_source_metadata():
    handler = get_strategy_handler("document_ingest_summary")
    assert handler is not None

    compact = handler(
        {
            "success": True,
            "bundle_id": "research-bundle",
            "bundle_path": "/tmp/work/research/research-bundle",
            "sources_path": "/tmp/work/research/research-bundle/sources.json",
            "citations_path": "/tmp/work/research/research-bundle/citations.json",
            "evidence_manifest_path": "/tmp/work/research/research-bundle/evidence_manifest.json",
            "evidence_record_path": "/tmp/work/research/research-bundle/evidence/src-1.json",
            "sources_count": 1,
            "citations_count": 1,
            "evidence_count": 1,
            "source": {
                "id": "src-1",
                "title": "Salesforce Open CTI Developer Guide PDF",
                "url": "https://resources.docs.salesforce.com/latest/latest/en-us/sfdc/pdf/api_cti.pdf",
                "origin": "https://resources.docs.salesforce.com/latest/latest/en-us/sfdc/pdf/api_cti.pdf",
                "file_name": "api_cti.pdf",
                "suffix": ".pdf",
                "media_type": "application/pdf",
                "local_relative_path": "research/research-bundle/downloads/api_cti.pdf",
                "parsed_relative_path": "research/research-bundle/parsed/api_cti.parsed.txt",
                "parse_success": True,
                "bundle_id": "research-bundle",
                "citation_style": "ieee",
            },
            "artifacts": [
                {"path": "/tmp/work/research/research-bundle/downloads/api_cti.pdf", "name": "api_cti.pdf", "media_type": "application/pdf"}
            ],
            "content_preview": "A" * 5000,
        },
        {"max_preview_chars": 100, "max_artifacts": 4},
    )

    assert compact["source"]["title"] == "Salesforce Open CTI Developer Guide PDF"
    assert compact["source"]["url"].endswith("api_cti.pdf")
    assert compact["source"]["media_type"] == "application/pdf"
    assert compact["source"]["local_relative_path"].startswith("research/")
    assert compact["artifacts"][0]["name"] == "api_cti.pdf"
    assert len(compact["content_preview"]) <= 103


def test_subthread_context_compression_preserves_structured_evidence_without_raw_transcript_bloat():
    handler = get_strategy_handler("subthread_context_summary")
    assert handler is not None

    compact = handler(
        {
            "parent_session_id": "parent-1",
            "evidence_profile": "research_document",
            "count": 2,
            "accepted_count": 1,
            "rejected_count": 1,
            "accepted_subthreads": [
                {
                    "session_id": "child-a",
                    "status": "completed",
                    "title": "Research benefits",
                    "task": "Research ticketing API benefits",
                    "final_response": "A" * 3000,
                    "message_count": 12,
                    "tool_call_count": 4,
                    "tool_names": ["web_search", "ingest_document_source"],
                    "quality": {
                        "profile": "research_document",
                        "accepted": True,
                        "response_kind": "substantive",
                        "rejection_reasons": [],
                        "has_tool_evidence": True,
                        "is_source_grounded": True,
                        "successful_tool_names": ["web_search", "ingest_document_source"],
                        "credible_source_count": 1,
                        "source_urls": ["https://developer.example.com/ticketing-api"],
                        "source_candidates": [
                            {
                                "url": "https://developer.example.com/ticketing-api",
                                "title": "Ticketing API Integration Guide",
                                "snippet": "Developer documentation for ticketing integration.",
                            }
                        ],
                        "credible_source_candidates": [
                            {
                                "url": "https://developer.example.com/ticketing-api",
                                "title": "Ticketing API Integration Guide",
                                "snippet": "Developer documentation for ticketing integration.",
                            }
                        ],
                    },
                }
            ],
            "rejected_subthreads": [
                {
                    "session_id": "child-b",
                    "status": "completed",
                    "title": "Research risks",
                    "task": "Research ticketing API risks",
                    "final_response": "B" * 3000,
                    "message_count": 2,
                    "tool_call_count": 1,
                    "tool_names": ["web_search"],
                    "quality": {
                        "profile": "research_document",
                        "accepted": False,
                        "response_kind": "greeting_only",
                        "rejection_reasons": ["greeting_only_response", "not_source_grounded"],
                    },
                }
            ],
            "summary": {
                "completed": 2,
                "failed": 0,
                "active": 0,
                "accepted": 1,
                "rejected": 1,
                "tool_names": ["ingest_document_source", "web_search"],
            },
        },
        {"max_response_chars": 120, "max_sources_per_thread": 4},
    )

    accepted = compact["accepted_subthreads"][0]
    rejected = compact["rejected_subthreads"][0]
    assert compact["accepted_count"] == 1
    assert compact["subthreads"] == compact["accepted_subthreads"]
    assert len(accepted["final_response"]) <= 123
    assert "final_response" not in rejected
    assert accepted["quality"]["source_candidates"] == [
        {
            "url": "https://developer.example.com/ticketing-api",
            "title": "Ticketing API Integration Guide",
            "snippet": "Developer documentation for ticketing integration.",
        }
    ]
    assert rejected["quality"]["rejection_reasons"] == ["greeting_only_response", "not_source_grounded"]
