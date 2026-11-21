"""The sample Workspace's Document updater agent (test and demo bootstrap data)."""

# ruff: noqa: E501

from __future__ import annotations

DOCUMENT_UPDATER_DEFINITION: dict[str, object] = {
    "name": "Document Updater",
    "description": "Analyzes the latest code changes and prepares targeted documentation updates for Confluence.",
    "goal": "Understand the latest code changes, derive the documentation needs, and update or draft the necessary "
    "Confluence changes.",
    "agent_type": "change",
    "thinking_level": "deep",
    "branch_prefix": "octryx",
    "steps": [
        {
            "name": "Collect changes",
            "step_type": "analysis",
            "instructions": "Fetch the relevant commits or pull requests for the requested period or branch. "
            "Prepare the affected repository if needed and determine the concrete code or "
            "configuration changes. Add Jira context if needed.",
            "success_criteria": "The relevant technical changes, affected components and concrete file changes are "
            "clearly identified.",
            "allowed_tools": [
                "list_recent_bitbucket_commits",
                "search_jira_tickets",
                "prepare_bitbucket_repository",
                "git_change_summary",
                "list_workspace_git_commits",
                "analyze_workspace_repository",
            ],
        },
        {
            "name": "Derive documentation needs",
            "step_type": "documentation",
            "instructions": "Check which runbooks, architecture or operations notes in Confluence are affected and "
            "whether there are knowledge gaps. Use the Confluence search instead of guessing page "
            "IDs or titles.",
            "success_criteria": "It is clear which pages are to be updated, created or left unchanged, and the "
            "concrete target pages are identified.",
            "allowed_tools": ["knowledge_search", "search_confluence", "list_confluence_pages", "get_confluence_page"],
        },
        {
            "name": "Update Confluence",
            "step_type": "change",
            "instructions": "Apply the necessary changes to the Confluence pages already identified, precisely and "
            "traceably. Use the page lists or concrete page contents from the previous step "
            "instead of starting a new broad search. If no content change is needed, end the step "
            "with a clear justification.",
            "success_criteria": "The affected pages were updated, or there is a clear justification why no change "
            "was possible.",
            "allowed_tools": [
                "list_confluence_pages",
                "get_confluence_page",
                "update_confluence_page",
                "create_confluence_page",
            ],
        },
    ],
    "system_prompt": "Work documentation-first. Link code, ticket and Confluence context cleanly and do not propose "
    "speculative documentation changes.",
    "output_prompt": "Answer with: 1. changed scope, 2. affected Confluence pages, 3. proposed or applied "
    "documentation change, 4. open questions.",
}
