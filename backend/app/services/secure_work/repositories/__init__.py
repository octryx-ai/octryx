"""The one repository record.

A repository is declared once, as a ``code_repositories`` row of its Workspace (created from a Knowledge git
source), and edited in Settings → Workspace → Repositories. Its **coding setup** (how the agent builds, tests and
lints it, its owners and reviewers, branch rules and report paths) lives on that record
(``config_json.coding_setup``). ``record.py`` reads and saves it.
"""
