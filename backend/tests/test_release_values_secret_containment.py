"""Repository invariants for deployment secret containment.

These tests guard the repository-side contract: machine-local Helm values stay
untracked and unpackaged, tracked deployment material carries placeholders only, and
every guard that enforces this is a normal file that a plain ``git add`` can commit.
No value text is read back, asserted on, or printed; only placeholder classifications
and reason codes are used.

The synthetic scanner behaviour lives in ``test_secret_containment_contract.py``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from secret_containment import contract, package_scan, tracked_scan, values_scan  # noqa: E402

TRACKED_CHECKER = REPO_ROOT / "scripts" / "check_release_values_secrets.py"
PACKAGE_CHECKER = REPO_ROOT / "scripts" / "check_chart_package_inputs.py"
# The release chart under deployment/helm/octryx.
CHART_DIR = REPO_ROOT / "deployment" / "helm" / "octryx"
LOCAL_VALUES_RELATIVE = "deployment/helm/octryx/values.local.yaml"
EXAMPLE_VALUES = REPO_ROOT / "deployment" / "helm" / "values.example.yaml"

EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"

# Every file that has to land together with the removal of the tracked local values.
GUARD_FILES = (
    ".gitignore",
    "deployment/helm/octryx/.helmignore",
    "scripts/check_chart_package_inputs.py",
    "scripts/check_release_values_secrets.py",
    "scripts/secret_containment/__init__.py",
    "scripts/secret_containment/contract.py",
    "scripts/secret_containment/env_scan.py",
    "scripts/secret_containment/file_kinds.py",
    "scripts/secret_containment/package_scan.py",
    "scripts/secret_containment/report.py",
    "scripts/secret_containment/tracked_scan.py",
    "scripts/secret_containment/values_scan.py",
    "scripts/secret_containment/yaml_lines.py",
)

# Tracked deployment files whose secret-bearing entries must be placeholders.
PLACEHOLDER_ONLY_FILES = (
    "deployment/helm/octryx/values.yaml",
    "deployment/helm/values.example.yaml",
    ".env.example",
    ".env.development.example",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)


def _tracked_files() -> list[str]:
    return [entry for entry in _git("ls-files", "-z").stdout.split("\0") if entry]


def test_no_local_values_file_is_tracked() -> None:
    tracked_local = [path for path in _tracked_files() if path.endswith((".local.yaml", ".local.yml"))]
    assert tracked_local == [], f"machine-local values files are tracked: {tracked_local}"


def test_local_values_path_is_git_ignored() -> None:
    assert _git("check-ignore", "-q", LOCAL_VALUES_RELATIVE).returncode == 0, (
        f"{LOCAL_VALUES_RELATIVE} is not covered by .gitignore"
    )


@pytest.mark.parametrize("guard", GUARD_FILES)
def test_guard_file_exists_and_is_addable(guard: str) -> None:
    """Each guard must be a real, non-ignored file, not an intent-to-add placeholder.

    ``git add -N`` registers a path with an empty blob. Committing such an entry drops
    it silently, so the removal of the tracked secret file could land without the
    guards that keep it out. A guard is only acceptable as a normal file.
    """
    path = REPO_ROOT / guard
    assert path.is_file(), f"{guard} is missing"
    assert path.stat().st_size > 0, f"{guard} is empty"
    assert _git("check-ignore", "-q", guard).returncode != 0, f"{guard} is git-ignored and could not be committed"
    staged = _git("ls-files", "-s", "--", guard).stdout.split()
    if staged:
        assert staged[1] != EMPTY_BLOB, f"{guard} is staged as an empty blob (intent-to-add), so a commit would drop it"


@pytest.mark.parametrize("chart_dir", ["deployment/helm/octryx"])
def test_chart_helmignore_excludes_local_values(chart_dir: str) -> None:
    helmignore = REPO_ROOT / chart_dir / ".helmignore"
    assert helmignore.is_file(), f"{chart_dir} has no .helmignore, so `helm package` would embed local values"
    patterns = {line.strip() for line in helmignore.read_text(encoding="utf-8").splitlines()}
    assert "*.local.yaml" in patterns
    assert "*.local.yml" in patterns
    assert "values.local.yaml" in patterns
    # .gitignore ignores dotfiles by default, so the exclusion list must be allowlisted
    # or a fresh clone would package local values again.
    relative = f"{chart_dir}/.helmignore"
    assert _git("check-ignore", "-q", relative).returncode != 0, (
        f"{relative} is git-ignored and would be missing from a clone"
    )


def test_example_values_file_is_placeholder_only() -> None:
    assert EXAMPLE_VALUES.is_file(), "the commented example values for the chart are missing"
    relative = EXAMPLE_VALUES.relative_to(REPO_ROOT).as_posix()
    findings = tracked_scan.check_paths(REPO_ROOT, [relative])
    assert findings == [], [finding.render() for finding in findings]


def test_chart_never_renders_a_secret_from_values() -> None:
    """The chart reads one existing Secret by name; secret material never passes through values."""
    for template in sorted((CHART_DIR / "templates").glob("*")):
        text = template.read_text(encoding="utf-8")
        assert not re.search(r"^kind:\s*Secret\s*$", text, flags=re.MULTILINE), f"{template.name} renders a Secret"
        assert ".Values.secrets" not in text, (
            f"{template.name} reads secret material from values"
        )


def test_tracked_repository_has_no_secret_containment_findings() -> None:
    findings = tracked_scan.check_paths(REPO_ROOT, _tracked_files())
    assert findings == [], [finding.render() for finding in findings]


def test_tracked_checker_cli_passes_for_the_repository() -> None:
    result = subprocess.run(
        [sys.executable, str(TRACKED_CHECKER), "--root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("chart_dir", [CHART_DIR])
def test_package_checker_cli_passes_for_the_real_charts(chart_dir: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(PACKAGE_CHECKER), str(chart_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_chart_has_no_weak_default_secrets() -> None:
    """No template falls back to a hardcoded secret: a missing key fails the install instead."""
    assert dict(values_scan.weak_default_secret_keys(CHART_DIR)) == {}


def test_dropping_a_weak_default_key_from_the_chart_values_is_reported(tmp_path: Path) -> None:
    """Regression for the quiet path back to a chart's hardcoded fallback secrets."""
    chart = tmp_path / "octryx"
    (chart / "templates").mkdir(parents=True)
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: octryx\nversion: 0.0.1\n", encoding="utf-8")
    shutil.copy(CHART_DIR / ".helmignore", chart / ".helmignore")
    (chart / "templates" / "secrets.yaml").write_text(
        "data:\n  JWT_SECRET: {{ .Values.secrets.jwtSecret | default \"Y2hhbmdlbWU=\" | quote }}\n", encoding="utf-8"
    )
    (chart / "values.yaml").write_text("secrets:\n  other: \"<set-me>\"\n", encoding="utf-8")
    findings = package_scan.check_chart_directory(chart)
    assert [(finding.key, finding.reason) for finding in findings] == [
        ("jwtSecret", contract.REASON_MISSING_WEAK_DEFAULT)
    ]


@pytest.mark.parametrize("relative", PLACEHOLDER_ONLY_FILES)
def test_tracked_deployment_file_is_placeholder_only(relative: str) -> None:
    findings = tracked_scan.check_paths(REPO_ROOT, [relative])
    assert findings == [], [finding.render() for finding in findings]


def test_packaging_paths_call_the_package_input_check_before_helm_package() -> None:
    script = (REPO_ROOT / "scripts" / "local-build-push.sh").read_text(encoding="utf-8")
    assert script.index("check_chart_package_inputs.py") < script.index('helm package "$CHART_PATH"')


def test_chart_directories_declare_the_required_helmignore_patterns() -> None:
    for chart_dir in (CHART_DIR,):
        declared = package_scan.HelmIgnore.load(chart_dir).declared()
        missing = [pattern for pattern in package_scan.REQUIRED_HELMIGNORE_PATTERNS if pattern not in declared]
        assert missing == [], f"{chart_dir.name} .helmignore misses {missing}"
