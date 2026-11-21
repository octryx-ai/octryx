"""Tool definitions for the CI/CD pipeline domain."""

from __future__ import annotations

import copy

# ruff: noqa: E501


CICD_DEFINITIONS: dict[str, dict] = {
    "get_job_logs": {
        "type": "function",
        "function": {
            "name": "get_job_logs",
            "description": "Get raw CI job logs from GitHub Actions or GitLab CI",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "github or gitlab"},
                    "repository": {"type": "string"},
                    "owner": {"type": "string"},
                    "project": {"type": "string"},
                    "job_id": {"type": "string"},
                    "timeout_sec": {"type": "integer"},
                },
                "required": ["job_id"],
            },
        },
    },
    "get_pipeline_logs": {
        "type": "function",
        "function": {
            "name": "get_pipeline_logs",
            "description": "Aggregate CI pipeline or workflow logs from GitHub Actions, GitLab CI or Azure DevOps",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "github, gitlab or azure_devops"},
                    "repository": {"type": "string"},
                    "owner": {"type": "string"},
                    "project": {"type": "string"},
                    "run_id": {"type": "string"},
                    "pipeline_id": {"type": "string"},
                    "limit": {"type": "integer"},
                    "timeout_sec": {"type": "integer"},
                },
            },
        },
    },
    "trigger_workflow": {
        "type": "function",
        "function": {
            "name": "trigger_workflow",
            "description": "Trigger a GitHub Actions workflow or a GitLab pipeline",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "github or gitlab"},
                    "repository": {"type": "string"},
                    "owner": {"type": "string"},
                    "project": {"type": "string"},
                    "workflow_id": {"type": "string"},
                    "ref": {"type": "string"},
                    "branch": {"type": "string"},
                    "inputs": {"type": "object"},
                    "variables": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
    },
    "retry_job": {
        "type": "function",
        "function": {
            "name": "retry_job",
            "description": "Retry a GitHub Actions or GitLab CI job",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "github or gitlab"},
                    "repository": {"type": "string"},
                    "owner": {"type": "string"},
                    "project": {"type": "string"},
                    "job_id": {"type": "string"},
                },
                "required": ["job_id"],
            },
        },
    },
    "cancel_pipeline": {
        "type": "function",
        "function": {
            "name": "cancel_pipeline",
            "description": "Cancel a GitHub Actions workflow run or GitLab pipeline",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "github or gitlab"},
                    "repository": {"type": "string"},
                    "owner": {"type": "string"},
                    "project": {"type": "string"},
                    "run_id": {"type": "string"},
                    "pipeline_id": {"type": "string"},
                },
            },
        },
    },
    "list_artifacts": {
        "type": "function",
        "function": {
            "name": "list_artifacts",
            "description": "List CI artifacts for a GitHub Actions run or GitLab pipeline",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "github or gitlab"},
                    "repository": {"type": "string"},
                    "owner": {"type": "string"},
                    "project": {"type": "string"},
                    "run_id": {"type": "string"},
                    "pipeline_id": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_artifact": {
        "type": "function",
        "function": {
            "name": "get_artifact",
            "description": "Get metadata or download details for a GitHub Actions or GitLab artifact",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "github or gitlab"},
                    "repository": {"type": "string"},
                    "owner": {"type": "string"},
                    "project": {"type": "string"},
                    "artifact_id": {"type": "string"},
                    "job_id": {"type": "string"},
                },
            },
        },
    },
    "get_test_results": {
        "type": "function",
        "function": {
            "name": "get_test_results",
            "description": "Summarize CI test results for a GitHub Actions run or GitLab pipeline",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "github or gitlab"},
                    "repository": {"type": "string"},
                    "owner": {"type": "string"},
                    "project": {"type": "string"},
                    "run_id": {"type": "string"},
                    "pipeline_id": {"type": "string"},
                    "limit": {"type": "integer"},
                    "include_cases": {"type": "boolean", "description": "Also return the per-test results: "
                                      "GitHub's JUnit test-report artifacts, GitLab's pipeline test report"},
                    "artifact": {"type": "string", "description": "GitHub: the artifact holding the JUnit report"},
                },
            },
        },
    },
    "list_work_items": {
        "type": "function",
        "function": {
            "name": "list_work_items",
            "description": "List Azure DevOps work items for an allowed project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "work_item_type": {"type": "string"},
                    "state": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_jenkins_builds": {
        "type": "function",
        "function": {
            "name": "list_jenkins_builds",
            "description": (
                "List the recent builds of the alert target's Jenkins job in the alert window (read-only): "
                "number, status, timestamp, commit, url, optional test summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job": {
                        "type": "string",
                        "description": "One of the alert target's Jenkins jobs (default: the only one)",
                    },
                    "since": {
                        "type": "string",
                        "description": "RFC3339 time or a duration like 6h (default: the alert window)",
                    },
                    "until": {"type": "string", "description": "RFC3339 end (default: now)"},
                    "limit": {"type": "integer", "description": "At most 20 (default 10)"},
                    "include_tests": {"type": "boolean", "description": "Add each build's test counts"},
                },
                "required": [],
            },
        },
    },
    "list_pipelines": {
        "type": "function",
        "function": {
            "name": "list_pipelines",
            "description": "List Azure DevOps pipelines for an allowed project",
            "parameters": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
}


def get_cicd_definitions() -> dict[str, dict]:
    """Return OpenAI-compatible tool definitions for cicd tools."""
    # A fresh copy per call: callers may change the returned definitions without touching the shared table.
    return copy.deepcopy(CICD_DEFINITIONS)
