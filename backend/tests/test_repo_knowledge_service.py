from pathlib import Path

from app.services.repo_knowledge import discover_repo_knowledge_files, select_relevant_repo_knowledge_files


def test_discover_repo_knowledge_files_from_workspace_and_allowed_repositories(tmp_path: Path):
    workspace_knowledge_root = tmp_path / ".agents" / "knowledge"
    workspace_knowledge_root.mkdir(parents=True)
    (workspace_knowledge_root / "payments.md").write_text(
        "---\ntitle: Payment Runbook\nsummary: Payment handling notes\ntriggers: [payment, checkout]\ntags: [runbook]\nalways_include: true\n---\nUse the PSP status page before escalating payment incidents.\n",
        encoding="utf-8",
    )

    repo_knowledge_root = tmp_path / "var" / "repos" / "bitbucket" / "RIVER" / "service-config" / ".agents" / "knowledge"
    repo_knowledge_root.mkdir(parents=True)
    (repo_knowledge_root / "gitops.md").write_text(
        "---\ntitle: GitOps Branch Policy\nsummary: Branches define live state\ntriggers: [deploy, release]\ntags: [gitops, release]\npriority: 40\n---\nRelease and prod branches represent the effective deployment state for service-config.\n",
        encoding="utf-8",
    )

    entries = discover_repo_knowledge_files(
        workspace_root=str(tmp_path),
        project_config={
            "managed_repo_root": "var/repos/bitbucket",
            "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "service-config", "enabled": True}],
        },
    )

    assert {entry["title"] for entry in entries} == {"Payment Runbook", "GitOps Branch Policy"}
    gitops = next(entry for entry in entries if entry["title"] == "GitOps Branch Policy")
    assert gitops["repo_label"] == "RIVER/service-config"
    assert gitops["source_kind"] == "repository"


def test_select_relevant_repo_knowledge_files_loads_only_always_include_entries():
    entries = [
        {
            "title": "Payment Runbook",
            "summary": "",
            "content": "Use the PSP status page before escalating.",
            "excerpt": "Use the PSP status page before escalating.",
            "triggers": ["payment"],
            "tags": ["runbook"],
            "repo_scope": [],
            "always_include": True,
            "priority": 5,
            "source_kind": "workspace",
            "repo_label": None,
            "source_path": "/tmp/.agents/knowledge/payments.md",
            "relative_path": ".agents/knowledge/payments.md",
        },
        {
            "title": "GitOps Branch Policy",
            "summary": "",
            "content": "Release branches define the live state.",
            "excerpt": "Release branches define the live state.",
            "triggers": ["deploy", "release"],
            "tags": ["gitops"],
            "repo_scope": [],
            "always_include": False,
            "priority": 40,
            "source_kind": "repository",
            "repo_label": "RIVER/service-config",
            "source_path": "/tmp/var/repos/bitbucket/RIVER/service-config/.agents/knowledge/gitops.md",
            "relative_path": "var/repos/bitbucket/RIVER/service-config/.agents/knowledge/gitops.md",
        },
    ]

    # Triggers, tags and repository mentions activate nothing; always_include does.
    selected = select_relevant_repo_knowledge_files(entries=entries)
    assert [entry["title"] for entry in selected] == ["Payment Runbook"]

