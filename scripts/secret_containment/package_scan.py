"""Inspect the exact chart directory that is about to be packaged.

``helm package`` archives whatever is in the directory, not what git tracks. A
developer's or CI runner's working copy can therefore contain an untracked or
git-ignored ``values-local.yaml`` that ends up inside the published artifact. This
check runs immediately before packaging and looks at the real directory contents,
including untracked and ignored files.

Boundary, so legitimate charts do not produce findings:

* ``templates/``, ``charts/`` and ``crds/`` are chart machinery. Files there are
  expected; only machine-local secret material by file type is rejected, so a
  legitimate ``templates/secrets.yaml`` that renders from template references passes.
* At the chart root the policy is deny-by-default: known chart files, documentation,
  ``*.example`` / ``*.sample`` / ``*.template`` copies, names allowed explicitly on the
  command line, and git-tracked files are accepted. Anything else must be excluded by
  ``.helmignore``.
* Every accepted values file, env file and Secret manifest is still scanned against the
  placeholder contract — under its effective name, so an accepted ``app.env.example`` or
  ``mysecret.yaml.example`` is read as the env template or Secret manifest it is. A
  locally edited ``values.yaml`` cannot be packaged with real material either.
* File types no scanner can inspect (private keys, keystores, kubeconfigs) are rejected
  by name including under a documentation suffix: there is nothing to verify inside them,
  so ``tls.key.example`` is treated exactly like ``tls.key``.
* The chart's authoritative ``values.yaml`` must still declare every secret key the
  templates would otherwise default; a deleted key is reported like an empty one.

Values are never read back or printed; findings carry path, line, key name and reason.
"""

from __future__ import annotations

import fnmatch
import subprocess
from collections.abc import Mapping
from pathlib import Path

from .contract import (
    REASON_HELMIGNORE_GAP,
    REASON_MISSING_HELMIGNORE,
    REASON_MISSING_WEAK_DEFAULT,
    REASON_SECRET_MATERIAL_FILE,
    REASON_UNEXPECTED_CHART_FILE,
    Finding,
)
from .file_kinds import (
    effective_name,
    has_documentation_suffix,
    is_values_file,
    matches_any,
    scan_env_or_secret_path,
)
from .values_scan import (
    AUTHORITATIVE_VALUES_FILE,
    NO_KEYS,
    scan_values_file,
    weak_default_secret_keys,
)

# Subtrees that belong to the chart mechanism itself.
CHART_MACHINERY_DIRS = ("templates", "charts", "crds")

# Chart root files that are always expected.
ALLOWED_CHART_FILES = frozenset(
    {
        ".gitattributes",
        ".helmignore",
        "Chart.lock",
        "Chart.yaml",
        "LICENSE",
        "NOTICE",
        "requirements.lock",
        "requirements.yaml",
        "values.schema.json",
        "values.yaml",
    }
)
ALLOWED_CHART_GLOBS = ("*.md", "LICENSE*", "NOTICE*")

# File types this package has no scanner for: there is nothing inside them to verify,
# so the name is the whole decision. Rejected anywhere in the chart, and also under a
# documentation suffix — ``tls.key.example`` is as unverifiable as ``tls.key``.
OPAQUE_MATERIAL_PATTERNS = (
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "id_rsa*",
    "*kubeconfig*",
)

# Machine-local secret *input* by file type. Matched on the literal name only: a
# documentation copy of one of these is accepted on purpose and content-scanned instead,
# which is what makes ``values.local.yaml.example`` a usable guard.
LOCAL_INPUT_PATTERNS = (
    "*.local.yaml",
    "*.local.yml",
    "*.env",
    ".env*",
)

# Machine-local secret material by file type. Rejected anywhere in the chart.
SECRET_MATERIAL_PATTERNS = LOCAL_INPUT_PATTERNS + OPAQUE_MATERIAL_PATTERNS

# Additional rejects at the chart root, where a ``secrets.yaml`` is input, not a template.
ROOT_LOCAL_INPUT_PATTERNS = LOCAL_INPUT_PATTERNS + (
    "secret.yaml",
    "secret.yml",
    "secrets.yaml",
    "secrets.yml",
    "secrets.json",
    "values-local.yaml",
    "values-local.yml",
)
ROOT_OPAQUE_MATERIAL_PATTERNS = OPAQUE_MATERIAL_PATTERNS + (
    "*credential*",
    "*.netrc",
    ".dockercfg",
    "*.dockerconfigjson",
)
ROOT_SECRET_MATERIAL_PATTERNS = ROOT_LOCAL_INPUT_PATTERNS + ROOT_OPAQUE_MATERIAL_PATTERNS

# .helmignore must keep machine-local values out of the archive.
REQUIRED_HELMIGNORE_PATTERNS = ("*.local.yaml", "*.local.yml")


class HelmIgnore:
    """Minimal ``.helmignore`` matcher following helm's own pattern rules."""

    def __init__(self, patterns: list[str]) -> None:
        self.patterns = patterns

    @classmethod
    def load(cls, chart_dir: Path) -> HelmIgnore:
        path = chart_dir / ".helmignore"
        if not path.is_file():
            return cls([])
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return cls([line.strip() for line in lines if line.strip() and not line.strip().startswith("#")])

    def declared(self) -> set[str]:
        return {pattern.lstrip("/").rstrip("/") for pattern in self.patterns}

    def excludes(self, relative: str, is_dir: bool) -> bool:
        parts = Path(relative).parts
        # helm prunes matching directories, so an excluded ancestor excludes the file.
        for depth in range(len(parts)):
            candidate = "/".join(parts[: depth + 1])
            candidate_is_dir = is_dir or depth + 1 < len(parts)
            if self._matches(candidate, candidate_is_dir):
                return True
        return False

    def _matches(self, relative: str, is_dir: bool) -> bool:
        name = relative.rsplit("/", 1)[-1]
        for pattern in self.patterns:
            directory_only = pattern.endswith("/")
            cleaned = pattern.rstrip("/")
            if directory_only and not is_dir:
                continue
            if cleaned.startswith("/"):
                if fnmatch.fnmatchcase(relative, cleaned.lstrip("/")):
                    return True
                continue
            target = relative if "/" in cleaned else name
            if fnmatch.fnmatchcase(target, cleaned):
                return True
        return False


def _tracked_in(chart_dir: Path) -> frozenset[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(chart_dir), "ls-files", "-z"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return frozenset()
    return frozenset(entry for entry in result.stdout.split("\0") if entry)


def _contract_findings(
    chart_dir: Path,
    relative: str,
    weak_keys: Mapping[str, str],
    required_keys: Mapping[str, str],
) -> list[Finding]:
    """Scan one packaged file against the placeholder contract, under its effective name."""
    absolute = chart_dir / relative
    if is_values_file(Path(relative).name):
        required = required_keys if relative == AUTHORITATIVE_VALUES_FILE else NO_KEYS
        text = absolute.read_text(encoding="utf-8", errors="replace")
        return scan_values_file(relative, text, weak_keys, required)
    return scan_env_or_secret_path(relative, absolute)


def _is_accepted_root_file(name: str, relative: str, allowed_extra: frozenset[str], tracked: frozenset[str]) -> bool:
    if name in ALLOWED_CHART_FILES or matches_any(name, ALLOWED_CHART_GLOBS):
        return True
    if name in allowed_extra or relative in allowed_extra:
        return True
    if has_documentation_suffix(name):
        return True
    return relative in tracked


def check_chart_directory(
    chart_dir: Path,
    allowed_extra: frozenset[str] = frozenset(),
    ignore: HelmIgnore | None = None,
) -> list[Finding]:
    """Report packaging risks in the chart directory as it exists on disk right now."""
    if not (chart_dir / "Chart.yaml").is_file():
        raise ValueError(f"{chart_dir} is not a Helm chart directory (no Chart.yaml)")

    findings: list[Finding] = []
    helmignore = ignore if ignore is not None else HelmIgnore.load(chart_dir)
    if not (chart_dir / ".helmignore").is_file():
        findings.append(Finding(".helmignore", 0, "", REASON_MISSING_HELMIGNORE))
    else:
        declared = helmignore.declared()
        for required in REQUIRED_HELMIGNORE_PATTERNS:
            if required not in declared:
                findings.append(Finding(".helmignore", 0, required, REASON_HELMIGNORE_GAP))

    tracked = _tracked_in(chart_dir)
    weak_keys = weak_default_secret_keys(chart_dir)
    # A chart with weak template defaults and no values file at all has nothing holding
    # the placeholders, so the missing keys are reported against the file that is absent.
    if weak_keys and not (chart_dir / AUTHORITATIVE_VALUES_FILE).is_file():
        findings.extend(
            Finding(AUTHORITATIVE_VALUES_FILE, 0, chart_key, REASON_MISSING_WEAK_DEFAULT)
            for _, chart_key in sorted(weak_keys.items())
        )
    for absolute in sorted(path for path in chart_dir.rglob("*") if path.is_file()):
        relative = absolute.relative_to(chart_dir).as_posix()
        if helmignore.excludes(relative, is_dir=False):
            continue
        name = absolute.name
        in_machinery = Path(relative).parts[0] in CHART_MACHINERY_DIRS and "/" in relative
        local_input = LOCAL_INPUT_PATTERNS if in_machinery else ROOT_LOCAL_INPUT_PATTERNS
        opaque = OPAQUE_MATERIAL_PATTERNS if in_machinery else ROOT_OPAQUE_MATERIAL_PATTERNS
        if matches_any(name, local_input) or matches_any(effective_name(name), opaque):
            findings.append(Finding(relative, 0, "", REASON_SECRET_MATERIAL_FILE))
            continue
        findings.extend(_contract_findings(chart_dir, relative, weak_keys, weak_keys))
        if in_machinery:
            continue
        if not _is_accepted_root_file(name, relative, allowed_extra, tracked):
            findings.append(Finding(relative, 0, "", REASON_UNEXPECTED_CHART_FILE))
    return findings
