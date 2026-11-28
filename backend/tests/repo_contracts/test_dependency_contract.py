"""Every third-party distribution ``backend/app`` imports must be declared by ``backend/pyproject.toml``.
Runs offline with ``--noconftest``; the negative controls prove the scanner can fail."""

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


def test_backend_app_declares_every_third_party_distribution_it_imports():
    findings = undeclared_imports()
    assert not findings, (
        "backend/app imports distributions that backend/pyproject.toml neither declares nor allowlists.\n"
        "Declare them in [project].dependencies, or add a reasoned entry to "
        "dependency_gates.import_contract.OPTIONAL_IMPORT_ALLOWLIST:\n" + format_findings(findings)
    )


@pytest.mark.parametrize("distribution", ISSUE_763_DISTRIBUTIONS)
def test_the_office_distributions_of_issue_763_are_base_dependencies(distribution: str):
    assert canonical_name(distribution) in read_declared_contract().base, (
        f"{distribution} must stay a [project].dependencies entry: an extra would not be installed"
    )


def test_no_required_import_is_covered_only_by_an_allowlist_entry():
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
    imported = {site.distribution for site in scan_imports()}
    stale = sorted(set(OPTIONAL_IMPORT_ALLOWLIST) - imported)
    assert not stale, f"allowlist entries for distributions backend/app no longer imports: {stale}"


def test_every_allowlist_entry_carries_a_reason():
    empty = sorted(name for name, reason in OPTIONAL_IMPORT_ALLOWLIST.items() if len(reason.strip()) < 30)
    assert not empty, f"allowlist entries without a usable reason: {empty}"


def test_the_scanner_sees_the_real_import_surface():
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
