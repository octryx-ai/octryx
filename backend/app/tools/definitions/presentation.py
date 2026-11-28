"""Tool definitions for the deterministic presentation composer."""

from __future__ import annotations

# ruff: noqa: E501


def get_presentation_definitions() -> dict[str, dict]:
    return {
        "create_presentation": {
            "type": "function",
            "function": {
                "name": "create_presentation",
                "description": (
                    "Compose a brand-compliant, evidence-backed PowerPoint deck from the corporate template and "
                    "the evidence collected in this turn. Use this instead of writing pptx scripts by hand. "
                    "Requires an aws_topology_snapshot result in the same turn; embeds diagrams created in this "
                    "turn and knowledge_search facts when present. Returns the deck artifact, the slide list, "
                    "quality findings, and the evidence sources used."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Subject of the deck, e.g. 'AWS-Architektur'.",
                        },
                        "content": {
                            "type": "object",
                            "description": (
                                "For a NON-architecture topic (release notes, task distribution, onboarding, …): the "
                                "sourced content to compose. {title, subtitle?, sections: [{heading, bullets: "
                                "[{text, source}]}], open_points?}. Every claim should carry a source; a section "
                                "without one becomes a visible [SOURCE MISSING] marker. Omit for AWS decks (those use "
                                "the aws_topology_snapshot)."
                            ),
                        },
                        "profile_id": {
                            "type": "string",
                            "description": "Corporate identity profile to take the template from; defaults to the active profile.",
                        },
                        "template_path": {
                            "type": "string",
                            "description": "Explicit .potx/.pptx template path; overrides the profile template.",
                        },
                        "max_slides": {
                            "type": "integer",
                            "description": "Upper bound on slides (2-40). The closing open-points slide is always kept.",
                        },
                    },
                    "required": ["topic"],
                },
            },
        },
    }
