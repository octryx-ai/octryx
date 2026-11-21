"""Decide which secret containment scanner applies to a deployment file.

A file name carries two independent facts: what the file *is* — Helm release values,
an env template, a Kubernetes Secret manifest — and whether it is a documentation
copy of such a file (``values.yaml.example``, ``app.env.template``). A documentation
suffix only says "this copy is not the deployed one". It does not change what the
content is.

Both preflights accept documentation copies on purpose: a sanitized example is how a
deployment flow stays usable without tracking the real input. Accepting a file is
therefore not the same as trusting it. Every accepted documentation copy is classified
under its *effective* name — the name with the documentation suffixes removed — so it
reaches the same scanner as the file it documents. Gating on the literal suffix before
stripping is what let a chart-root ``app.env.example`` and ``mysecret.yaml.example``,
and a tracked ``*.env.example`` / ``*.yaml.template``, through both scanners unread.

One deliberate exception: a machine-local file name (``*.local.yaml``) is matched on
the *literal* name, because the sanitized ``values.local.yaml.example`` is the guard
that replaces the untracked original and must stay trackable and packageable.

Values are never read back or printed; see ``contract``.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from .contract import Finding
from .env_scan import (
    ENV_FILE_PATTERNS,
    looks_like_secret_manifest,
    scan_env_file,
    scan_secret_manifest,
)
from .values_scan import VALUES_FILE_PATTERNS

# Suffixes that mark a documentation copy of a real input file.
DOCUMENTATION_SUFFIXES = (".example", ".sample", ".template")

# Suffixes that make a file a YAML document, and therefore a Secret manifest candidate.
YAML_SUFFIXES = (".yaml", ".yml")


def matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatch(lowered, pattern.lower()) for pattern in patterns)


def effective_name(name: str) -> str:
    """Return the name with documentation suffixes removed.

    ``values.yaml.example`` becomes ``values.yaml``. Stacked suffixes are all removed,
    so ``secrets.env.example.template`` becomes ``secrets.env``. A name that is nothing
    but a suffix (``.example``) is returned unchanged.
    """
    result = name
    while True:
        lowered = result.lower()
        for suffix in DOCUMENTATION_SUFFIXES:
            if lowered.endswith(suffix) and len(result) > len(suffix):
                result = result[: -len(suffix)]
                break
        else:
            return result


def has_documentation_suffix(name: str) -> bool:
    return effective_name(name) != name


def is_values_file(name: str) -> bool:
    """True for a Helm release values file, including a documentation copy of one."""
    return matches_any(effective_name(name), VALUES_FILE_PATTERNS)


def is_env_file(name: str) -> bool:
    """True for a ``KEY=value`` env template, including a documentation copy of one."""
    return matches_any(effective_name(name), ENV_FILE_PATTERNS)


def has_scannable_content(name: str) -> bool:
    """True when a content scanner exists for this file's effective kind."""
    effective = effective_name(name)
    return matches_any(effective, ENV_FILE_PATTERNS) or effective.lower().endswith(
        YAML_SUFFIXES
    )


def scan_env_or_secret_path(path: str, absolute: Path) -> list[Finding]:
    """Scan an env template or a ``kind: Secret`` document under its effective name.

    Returns no findings for a file that is neither. An env-named file continues through the
    env scanner even when it also looks like a manifest; one YAML-looking line must not turn
    off the ``KEY=value`` credential contract. The content is read only when a scanner applies,
    so unrelated chart payloads are never decoded.
    """
    name = Path(path).name
    if not has_scannable_content(name):
        return []
    text = absolute.read_text(encoding="utf-8", errors="replace")
    findings: list[Finding] = []
    if looks_like_secret_manifest(text):
        findings.extend(scan_secret_manifest(path, text))
    if is_env_file(name):
        # A file with an env name remains subject to the env contract even when
        # some of its lines also look like YAML. In particular, broadening the
        # manifest gate to Kubernetes ``kind: List`` must not let an adversarial
        # ``kind: List`` line hide a following ``KEY=value`` credential.
        findings.extend(scan_env_file(path, text))
    return findings
