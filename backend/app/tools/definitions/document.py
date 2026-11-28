"""Tool definitions for the deterministic Word document composer."""

from __future__ import annotations

# ruff: noqa: E501


def get_document_definitions() -> dict[str, dict]:
    return {
        "create_document": {
            "type": "function",
            "function": {
                "name": "create_document",
                "description": (
                    "Compose a brand-compliant, evidence-backed Word document from the corporate template and "
                    "the evidence collected in this turn. Use this instead of writing docx scripts by hand. "
                    "Requires an aws_topology_snapshot result in the same turn; embeds diagrams from our own "
                    "pipeline and knowledge_search facts when present. A profile may hold several Word templates "
                    "for different purposes: pass `template` (id or name) to choose one. If several exist and none "
                    "is named, the tool returns the template catalog with each template's purpose description so "
                    "you can call it again with the fitting `template`."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Subject of the document, e.g. 'AWS-Architektur'.",
                        },
                        "content": {
                            "type": "object",
                            "description": (
                                "For a NON-architecture topic (release notes, task distribution, onboarding, …): the "
                                "sourced content to compose. {title, subtitle?, sections: [{heading, text?, bullets: "
                                "[{text, source}]}], open_points?}. Every claim should carry a source. Omit for AWS "
                                "documents (those use the aws_topology_snapshot)."
                            ),
                        },
                        "template": {
                            "type": "string",
                            "description": "Which Word template to use (template_id or display name) when the profile has several for different purposes.",
                        },
                        "profile_id": {
                            "type": "string",
                            "description": "Corporate identity profile to take the template from; defaults to the active profile.",
                        },
                        "template_path": {
                            "type": "string",
                            "description": "Explicit .docx/.dotx template path; overrides the profile template.",
                        },
                    },
                    "required": ["topic"],
                },
            },
        },
    }
