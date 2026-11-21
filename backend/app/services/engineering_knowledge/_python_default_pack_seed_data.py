"""Python Engineering Knowledge Pack seed data."""

from __future__ import annotations

from typing import Any

PYTHON312_ENGINEERING_PACK_KEY = "python-3-12-engineering-quality"
PYTHON312_TARGETS = {"python": "3.12"}
PYTHON312_SOURCE_VERSIONS = {"python": "3.11"}

PYTHON312_SOURCE_POLICY: dict[str, Any] = {
    "trust_tiers": ["official", "vendor", "internal"],
    "allow_community_sources": False,
    "prefer_primary_sources": True,
    "min_archived_sources": 4,
}

PYTHON312_FRESHNESS_POLICY: dict[str, Any] = {
    "ttl_days": 30,
    "warning_days": 21,
    "refresh_required_before_use": False,
}

PYTHON312_RETRIEVAL_POLICY: dict[str, Any] = {
    "default_context_budget_tokens": 8_000,
    "max_items": 8,
    "prefer_exact_target_versions": True,
    "required_tags": [
        "runtime",
        "packaging",
        "testing",
        "linting",
        "typing",
        "security",
    ],
}

PYTHON312_RESOLUTION_POLICY: dict[str, Any] = {
    "ask_user_on_ambiguity": True,
    "manual_pack_selection_required": False,
    "exact_target_versions_required": True,
    "allow_floating_patch_fallback": False,
}

PYTHON312_TOOLCHAIN_POLICY: dict[str, Any] = {
    "profiles": {
        "python": {
            "language": "python",
            "runtime_version": "3.12",
            "package_manager": "uv",
            "supported_package_managers": ["uv", "poetry", "pip"],
            "dependency_files": ["pyproject.toml", "requirements.txt", "setup.py"],
            "dependency_lock_files": ["uv.lock", "poetry.lock", "requirements.lock", "Pipfile.lock"],
            "test_runner": "pytest",
            "linter": "ruff",
            "formatter": "ruff",
            "type_checker": "mypy",
            "sast_runners": ["bandit", "semgrep"],
            "migration_recipes": ["python-runtime-3.12-compatibility-audit"],
            "docs_source_manifest": [
                "python-3-12-docs",
                "python-3-12-whats-new",
                "python-packaging-user-guide",
                "ruff-documentation",
            ],
            "validation_gates": [
                {
                    "name": "baseline_tests",
                    "tool": "test",
                    "required": True,
                    "stage": "before_change",
                    "requires_baseline_green": True,
                },
                {
                    "name": "post_migration_tests",
                    "tool": "test",
                    "required": True,
                    "stage": "after_change",
                },
                {
                    "name": "lint_and_format_check",
                    "tool": "ruff",
                    "required": True,
                    "stage": "after_change",
                },
                {
                    "name": "type_check",
                    "tool": "mypy",
                    "required": False,
                    "stage": "after_change",
                },
            ],
        }
    }
}

PYTHON312_SOURCE_SPECS: list[dict[str, Any]] = [
    {
        "source_key": "python-3-12-docs",
        "title": "Python 3.12 Documentation",
        "source_uri": "https://docs.python.org/3.12/",
        "source_type": "documentation",
        "trust_tier": "official",
        "version_label": "3.12",
        "metadata": {"coordinate": "python", "target_version": "3.12"},
        "tags": ["python", "runtime", "testing", "typing"],
        "summary": "Use Python 3.12 documentation as the exact runtime and standard library baseline.",
    },
    {
        "source_key": "python-3-12-whats-new",
        "title": "What's New In Python 3.12",
        "source_uri": "https://docs.python.org/3.12/whatsnew/3.12.html",
        "source_type": "release_notes",
        "trust_tier": "official",
        "version_label": "3.12",
        "metadata": {"coordinate": "python", "target_version": "3.12"},
        "tags": ["python", "runtime", "migration", "typing"],
        "summary": "Review Python 3.12 language, typing, runtime, and deprecation changes before edits.",
    },
    {
        "source_key": "python-packaging-user-guide",
        "title": "Python Packaging User Guide",
        "source_uri": "https://packaging.python.org/en/latest/",
        "source_type": "documentation",
        "trust_tier": "official",
        "version_label": "latest",
        "metadata": {"coordinate": "python_packaging", "target_version_source": "python_3.12"},
        "tags": ["python", "packaging", "dependency-management", "testing"],
        "summary": "Use packaging guidance before changing pyproject, build backends, or lock-file strategy.",
    },
    {
        "source_key": "ruff-documentation",
        "title": "Ruff Documentation",
        "source_uri": "https://docs.astral.sh/ruff/",
        "source_type": "tooling_documentation",
        "trust_tier": "vendor",
        "version_label": "current",
        "metadata": {"coordinate": "ruff", "target_version_source": "toolchain_policy"},
        "tags": ["python", "linting", "formatting", "testing"],
        "summary": "Use Ruff as the default lint and format gate for Python engineering tasks.",
    },
]
