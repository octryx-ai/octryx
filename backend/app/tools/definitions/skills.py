"""Tool definitions for skill discovery in the published skill catalog."""

from __future__ import annotations


def get_skills_definitions() -> dict[str, dict]:
    return {
        "skill_search": {
            "type": "function",
            "function": {
                "name": "skill_search",
                "description": (
                    "Search the published Octryx skill catalog. Returns metadata only (incl. the reference "
                    "files a skill offers); use skill_get to load one content level after selecting a relevant skill."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "category": {"type": "string", "description": "Category key, e.g. iac or iac.terraform."},
                        "source": {"type": "string", "enum": ["base", "connector", "custom"]},
                        "project_id": {"type": "string"},
                        "limit": {"type": "integer"},
                        "diagnostics": {
                            "type": "boolean",
                            "description": "Admin/operator-only; search always returns published skills.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        "skill_get": {
            "type": "function",
            "function": {
                "name": "skill_get",
                "description": (
                    "Load exactly one content level for a skill returned by skill_search, or one of its reference "
                    "files with resource (a path listed in the search result's resources)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string"},
                        "id": {"type": "string", "description": "Alias for skill_id."},
                        "name": {"type": "string"},
                        "project_id": {"type": "string"},
                        "content_level": {"type": "string", "enum": ["summary", "card", "full"]},
                        "resource": {"type": "string", "description": "A reference file path, e.g. references/x.md."},
                        "diagnostics": {
                            "type": "boolean",
                            "description": (
                                "Admin/operator-only: load the latest version of a skill that is not delivered."
                            ),
                        },
                    },
                },
            },
        },
    }


__all__ = ["get_skills_definitions"]
