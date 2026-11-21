"""Every third-party distribution ``backend/app`` imports must be declared by ``backend/pyproject.toml``.

An undeclared module-level import on the ``app.main`` boot path (``lxml``) makes every install path that follows
the declared contract produce an image that exits at import. Hand-installed local virtual environments hide it,
and no other test can see it.

The classification rules and the reason for each allowlist entry live in ``dependency_gates.import_contract``. These
tests add the two things a scanner cannot assert about itself: that the live repository satisfies the contract, and
that the scanner actually fails when the contract is broken. The negative controls matter more than the positive
assertions — a scanner that silently classifies everything as fine would pass the positive assertions too.

Offline and without the application fixtures, because the check reads source and TOML and imports neither the scanned
code nor the distributions it reasons about:

    backend/.venv/bin/python -m pytest backend/tests/test_dependency_contract.py -q --noconftest
"""

from __future__ import annotations

import pytest

from dependency_gates.import_contract import (
    DEFERRED,
    OPTIONAL_IMPORT_ALLOWLIST,
    REQUIRED,
    format_findings,
    read_declared_contract,
    scan_imports,
    undeclared_imports,
)
from dependency_gates.manifest import PYPROJECT_PATH, canonical_name

# Distributions once found undeclared while the committed code imported them. Kept as an explicit regression
# list so the specific defect cannot come back unnoticed through an allowlist edit.
ISSUE_763_DISTRIBUTIONS = ("lxml", "python-pptx")


# --- the live repository ------------------------------------------------------------------------------------------


def test_backend_app_declares_every_third_party_distribution_it_imports():
    findings = undeclared_imports()
    assert not findings, (
        "backend/app imports distributions that backend/pyproject.toml neither declares nor allowlists.\n"
        "Declare them in [project].dependencies, or add a reasoned entry to "
        "dependency_gates.import_contract.OPTIONAL_IMPORT_ALLOWLIST:\n" + format_findings(findings)
    )


@pytest.mark.parametrize("distribution", ISSUE_763_DISTRIBUTIONS)
def test_the_office_distributions_of_issue_763_are_base_dependencies(distribution: str):
    """An extra would not reach the image build: lxml is on the boot path and create_presentation is registered by default."""
    assert canonical_name(distribution) in read_declared_contract().base, (
        f"{distribution} must stay a [project].dependencies entry: an extra would not be installed"
    )


def test_no_required_import_is_covered_only_by_an_allowlist_entry():
    """A `required` import cannot degrade gracefully, so an allowlist entry for one would be a hidden boot-path risk."""
    declared = read_declared_contract()
    offenders = [
        site
        for site in scan_imports()
        if site.kind == REQUIRED
        and site.distribution in OPTIONAL_IMPORT_ALLOWLIST
        and site.distribution not in declared.base
    ]
    assert not offenders, "allowlisted distributions imported unguarded at import time: " + ", ".join(
        f"{site.distribution} at {site.location}" for site in offenders
    )


def test_every_allowlist_entry_is_still_imported_somewhere():
    """A stale allowlist entry silently weakens the contract for a distribution nothing imports any more."""
    imported = {site.distribution for site in scan_imports()}
    stale = sorted(set(OPTIONAL_IMPORT_ALLOWLIST) - imported)
    assert not stale, f"allowlist entries for distributions backend/app no longer imports: {stale}"


def test_every_allowlist_entry_carries_a_reason():
    empty = sorted(name for name, reason in OPTIONAL_IMPORT_ALLOWLIST.items() if len(reason.strip()) < 30)
    assert not empty, f"allowlist entries without a usable reason: {empty}"


def test_the_scanner_sees_the_real_import_surface():
    """Guard against a scanner that finds nothing: the repository's own known import-time distributions must appear."""
    sites = scan_imports()
    assert len(sites) > 1000, f"expected the full backend/app import surface, scanned only {len(sites)} sites"
    required = {site.distribution for site in sites if site.kind == REQUIRED}
    for distribution in ("fastapi", "sqlalchemy", "pydantic", "lxml", "pyyaml"):
        assert distribution in required, f"{distribution} is imported at module level but was not classified required"
    deferred = {site.distribution for site in sites if site.kind == DEFERRED}
    assert "python-pptx" in deferred, "python-pptx is imported inside functions and must be classified deferred"


def test_the_declared_contract_reader_separates_base_from_extras():
    declared = read_declared_contract(PYPROJECT_PATH)
    assert "fastembed" in declared.extras and "fastembed" not in declared.base
    assert "fastapi" in declared.base
    # pytest is a dev extra and a dependency group; neither may leak into the base contract.
    assert "pytest" not in declared.base
