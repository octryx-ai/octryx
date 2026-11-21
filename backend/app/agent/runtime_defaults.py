"""Stable runtime defaults shared across agent mode, prompt, and tool policy paths."""

from __future__ import annotations

from dataclasses import dataclass

VALID_CAPABILITY_TYPES = {"diagnosis", "change", "plan", "admin"}
DEFAULT_AGENT_MODE_KEY = "diagnosis"


@dataclass(frozen=True, slots=True)
class SystemAgentModeDefinition:
    key: str
    name: str
    description: str
    capability_type: str
    prompt_instructions: str
    is_system: bool = True

    def as_record(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "capability_type": self.capability_type,
            "prompt_instructions": self.prompt_instructions,
            "is_system": self.is_system,
        }


SYSTEM_AGENT_MODE_DEFINITIONS = (
    SystemAgentModeDefinition(
        key="diagnosis",
        name="Diagnosis",
        description="Read-only investigation mode for analysis, triage, and evidence gathering.",
        capability_type="diagnosis",
        prompt_instructions=(
            "Investigate, correlate, explain, and use only read-only tools "
            "unless a different mode is explicitly chosen."
        ),
    ),
    SystemAgentModeDefinition(
        key="change",
        name="Change",
        description="Controlled execution mode for implementation and modifications.",
        capability_type="change",
        prompt_instructions=(
            "Make controlled changes when the user request is clear. Prefer safe, auditable execution and verification."
        ),
    ),
    SystemAgentModeDefinition(
        key="plan",
        name="Plan",
        description="Planning mode for read-only exploration and execution planning without making changes.",
        capability_type="plan",
        prompt_instructions=("Explore with read-only tools, produce a concrete plan, and avoid write operations."),
    ),
    SystemAgentModeDefinition(
        key="knowledge",
        name="Knowledge",
        description="Knowledge and documentation analysis mode with read-heavy behavior.",
        capability_type="diagnosis",
        prompt_instructions=(
            "Focus on documentation and cross-referencing stored knowledge before raw source reads."
        ),
    ),
    SystemAgentModeDefinition(
        key="documentation",
        name="Documentation",
        description="Documentation update mode for structured document changes.",
        capability_type="change",
        prompt_instructions=(
            "Focus on producing or updating documentation with explicit scope, affected sources, and clear deltas."
        ),
    ),
    SystemAgentModeDefinition(
        key="chat",
        name="Chat",
        description="General conversational mode with diagnosis-style read-only capabilities.",
        capability_type="diagnosis",
        prompt_instructions=(
            "Handle general chat requests pragmatically and only expand into tool-based investigation when needed."
        ),
    ),
    SystemAgentModeDefinition(
        key="coding",
        name="Coding",
        description="Implementation-heavy mode for code and repository work.",
        capability_type="change",
        prompt_instructions=(
            "Focus on code changes, repository workflows, and verification. "
            "Prefer direct implementation over abstract discussion."
        ),
    ),
    SystemAgentModeDefinition(
        key="admin",
        name="Admin",
        description=(
            "Full control-plane mode with broad registered-tool access and enterprise orchestration privileges."
        ),
        capability_type="admin",
        prompt_instructions=(
            "Operate as a platform administrator. Use the registered tools "
            "needed to inspect, configure, validate, and repair the system. "
            "Do not self-limit to diagnosis-only behavior, but continue to "
            "respect approval, audit, and security policy."
        ),
    ),
)
SYSTEM_AGENT_MODE_DEFINITIONS_BY_KEY = {definition.key: definition for definition in SYSTEM_AGENT_MODE_DEFINITIONS}
DEFAULT_AGENT_MODES = [definition.as_record() for definition in SYSTEM_AGENT_MODE_DEFINITIONS]


def get_system_agent_mode_definition(mode_key: str | None) -> SystemAgentModeDefinition | None:
    return SYSTEM_AGENT_MODE_DEFINITIONS_BY_KEY.get(str(mode_key or "").strip().lower())


CODING_INTELLIGENCE_TOOLS = {
    "analyze_workspace_repository",
    "analyze_codebase_patterns",
    "code_search",
    "code_symbol_definition",
    "code_references",
    "code_callers",
    "code_context",
    "code_explore",
    "code_trace",
    "code_graph_status",
    "code_impact",
    "code_impact_analysis",
    "code_file_outline",
}

CODING_WRITE_TOOLS = {
    "write_workspace_file",
    "edit_workspace_file",
    "multi_edit_workspace_file",
    "apply_patch_workspace",
}

CODE_FILE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".m",
    ".mdx",
    ".mm",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".xml",
    ".yaml",
    ".yml",
}

CODE_FILE_NAMES = {
    "Dockerfile",
    "Makefile",
    "build.gradle",
    "build.gradle.kts",
    "cargo.toml",
    "compose.yaml",
    "compose.yml",
    "go.mod",
    "go.sum",
    "gradle.properties",
    "mvnw",
    "mvnw.cmd",
    "package-lock.json",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
    "settings.gradle",
    "settings.gradle.kts",
    "tsconfig.json",
}

CODE_DIRECTORY_TOKENS = {
    "app",
    "backend",
    "client",
    "cmd",
    "frontend",
    "include",
    "internal",
    "lib",
    "pkg",
    "server",
    "spec",
    "src",
    "test",
    "tests",
}

SUMMARY_DOMAIN_FALLBACK_TOOLS: dict[str, set[str]] = {
    "jira": {"search_jira_tickets", "get_jira_ticket"},
    "bitbucket": {"list_recent_bitbucket_commits", "list_bitbucket_commits"},
    "confluence": {"search_confluence", "get_confluence_page"},
}
