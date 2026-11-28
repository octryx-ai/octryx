"""Shared selections, canned tool results and tool-call accessors for the test_task_workflow_* modules."""

from app.services.research_policy.defaults import default_research_policy_profiles

# The topology variant is the selected definition's (``workflow_class``), never the prompt's.
_AWS_TOPOLOGY_SELECTION = {"workflow_id": "generic_diagram", "workflow_class": "aws_topology_diagram_request"}


# A diagram definition's type and icon library are configuration (or the user's closed decision),
# never read from the prompt; the tests below configure them explicitly.
def _developer_selection(diagram_type: str) -> dict:
    return {
        "workflow_id": "generic_diagram",
        "workflow_class": "developer_diagram_request",
        "developer_diagram_type": diagram_type,
    }


def _code_structure_selection(diagram_type: str) -> dict:
    return {
        "workflow_id": "generic_diagram",
        "workflow_class": "code_structure_diagram_request",
        "developer_diagram_type": diagram_type,
    }


def _tool_name(tool_calls):
    return str((tool_calls[0].get("function") or {}).get("name") or "").strip() if tool_calls else ""


def _tool_args(tool_calls):
    import json

    if not tool_calls:
        return {}
    return json.loads(str((tool_calls[0].get("function") or {}).get("arguments") or "{}"))


def _deep_research_policy_resolution() -> dict:
    for profile in default_research_policy_profiles():
        if profile["key"] == "deep-research-document":
            return {
                "source": "test",
                "profile_id": "profile-deep",
                "profile_key": profile["key"],
                "profile_name": profile["name"],
                "version_id": "version-deep-1",
                "version": profile["version"],
                "status": profile["status"],
                "spec": profile["spec"],
            }
    raise AssertionError("deep research policy profile is missing")
