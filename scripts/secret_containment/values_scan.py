"""Scan Helm release values files for secret material and weak-default exposure.

Three rules:

1. A secret-bearing key must hold an explicit placeholder (see ``contract``).
2. An *empty* secret-bearing key is only safe when nothing substitutes a value for
   it. When the chart's own templates fall back to a hardcoded default for that key
   (``{{ $sec.jwtSecret | default "..." }}``), an empty tracked value silently
   deploys that well-known default, so it is reported as a weak-default risk.
3. An *absent* key is the same exposure as an empty one, and it is the quieter of
   the two: deleting a line from the chart's authoritative ``values.yaml`` removes
   the placeholder and hands the deployment the template default, with nothing left
   in the file for rule 1 or 2 to look at. Every key the templates give a non-empty
   default is therefore required to be present in the authoritative values secret
   block, and to be accepted there by rule 1.

Rule 3 applies to the chart's own ``values.yaml`` only. Overlays (``values.<env>.yaml``,
``values.local.yaml.example``) carry what they override, and Helm merges them on top of
the authoritative file, so requiring the full key set from them would be wrong.

The template defaults themselves are only tested for emptiness; their content is
never read back or printed.

Lines are read through ``yaml_lines``, so a quoted key (``"openRouterApiKey": ...``) and a
flow mapping written on the block line (``secrets: {jwtSecret: ...}``, trailing comment
included) are the mapping entries they are instead of shapes the scanner walks past. A
secret-block line whose value cannot be read as a flow mapping is not dropped: it stays one
entry and is classified as the text it is, so a malformed ``secrets: {jwtSecret: ...`` is
reported against the block key rather than passed.

The same fail-closed rule applies after the block opens. A scalar continuation, explicit key,
or merge key that this bounded reader cannot attribute is reported as an unreadable secret
block. This matters even when the first scalar line is a placeholder: a continuation changes
the YAML value and must not inherit the first line's safe classification.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from pathlib import Path
from types import MappingProxyType

from .contract import (
    BLOCK_SCALAR_INDICATORS,
    EMPTY,
    MATERIAL,
    NON_SECRET_KEYS_IN_SECRET_BLOCK,
    REASON_BLOCK_NOT_PLACEHOLDER,
    REASON_BLOCK_SCALAR,
    REASON_BLOCK_UNREADABLE,
    REASON_EMPTY_WEAK_DEFAULT,
    REASON_MISSING_WEAK_DEFAULT,
    REASON_NOT_PLACEHOLDER,
    REASON_WEAK_VALUE,
    WEAK,
    Finding,
    classify_value,
    is_secret_material_key,
    normalise_key,
    strip_scalar,
)
from .yaml_lines import KeyLine, flow_mapping_entries, match_key_line

# File names scanned as release values. Documentation copies (``values.yaml.example``)
# are matched through ``file_kinds.is_values_file``, which strips the copy suffix first.
VALUES_FILE_PATTERNS = ("values*.yaml", "values*.yml")

# The one values file Helm always merges first, and therefore the only one that has to
# declare every secret key the chart templates would otherwise default.
AUTHORITATIVE_VALUES_FILE = "values.yaml"

NO_KEYS: Mapping[str, str] = MappingProxyType({})

# Top-level mappings whose leaves are secret material by contract.
SECRET_BLOCK_KEYS = ("secrets",)

# ``{{- $sec := .Values.secrets -}}`` style aliases for the secrets mapping.
_SECRET_ALIAS = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\s*:=\s*\.Values\.secrets\b")
_DEFAULT_CALL = (
    r"\.(?P<key>[A-Za-z0-9_]+)\s*\|\s*default\s+(?P<default>\"[^\"]*\"|'[^']*')"
)


def weak_default_secret_keys(chart_dir: Path) -> Mapping[str, str]:
    """Secret keys for which the chart templates supply a non-empty default.

    Maps the normalised key to the spelling the template uses, so a finding can name the
    key an operator would have to add back. The default value is only tested for
    emptiness and never stored.
    """
    templates = chart_dir / "templates"
    if not templates.is_dir():
        return NO_KEYS
    keys: dict[str, str] = {}
    for template in sorted(templates.rglob("*")):
        if not template.is_file() or template.suffix not in (".yaml", ".yml", ".tpl"):
            continue
        text = template.read_text(encoding="utf-8", errors="replace")
        prefixes = [re.escape(f"${alias}") for alias in _SECRET_ALIAS.findall(text)]
        prefixes.append(re.escape(".Values.secrets"))
        for prefix in prefixes:
            for match in re.finditer(prefix + _DEFAULT_CALL, text):
                if match.group("default")[1:-1] != "":
                    keys[normalise_key(match.group("key"))] = match.group("key")
    return keys


def chart_dir_for(path: Path) -> Path | None:
    """The chart directory a values file belongs to, or None when it is not in a chart."""
    parent = path.parent
    if (parent / "Chart.yaml").is_file() or (parent / "templates").is_dir():
        return parent
    return None


def _entries(line: KeyLine) -> list[tuple[str, str, bool]]:
    """The (key, value, is_child) entries one values line contributes.

    ``is_child`` marks an entry that sits *inside* the mapping the enclosing block names: an
    indented line is a child of the block above it, and a flow mapping written on the block
    line itself (``secrets: {jwtSecret: ...}``) holds children too. The distinction is what
    keeps rule 3's ``declared`` set to real secret keys.
    """
    flow = flow_mapping_entries(line.rest)
    if flow is None:
        return [(line.key, line.rest, bool(line.indent))]
    return [(entry.key, entry.value, True) for entry in flow]


def scan_values_file(
    path: str,
    text: str,
    weak_default_keys: Collection[str] = (),
    required_keys: Mapping[str, str] = NO_KEYS,
) -> list[Finding]:
    """Report secret-bearing keys in a release values file that are not safely contained.

    ``required_keys`` maps normalised key to chart spelling for keys that must be present
    in the secret block (rule 3); pass it only for the authoritative values file.
    """
    findings: list[Finding] = []
    declared: set[str] = set()
    block_key = ""
    block_indent: int | None = None
    pending_secret_indent: int | None = None
    pending_secret_key = ""
    unreadable_region = False
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        line = match_key_line(raw)
        if line is None:
            raw_indent = len(raw[: len(raw) - len(raw.lstrip(" \t"))].expandtabs(8))
            in_secret_block = block_key in SECRET_BLOCK_KEYS
            continuation = (
                pending_secret_indent is not None and raw_indent > pending_secret_indent
            )
            unreadable_block_entry = (
                in_secret_block
                and block_indent is not None
                and raw_indent > block_indent
            )
            if (continuation or unreadable_block_entry) and not unreadable_region:
                findings.append(
                    Finding(
                        path,
                        number,
                        pending_secret_key or block_key,
                        REASON_BLOCK_UNREADABLE,
                    )
                )
                unreadable_region = True
            continue
        indent = len(line.indent.expandtabs(8))
        if pending_secret_indent is not None and indent > pending_secret_indent:
            if not unreadable_region:
                findings.append(
                    Finding(path, number, pending_secret_key, REASON_BLOCK_UNREADABLE)
                )
            unreadable_region = True
            continue
        pending_secret_indent = None
        pending_secret_key = ""
        unreadable_region = False
        if not line.indent:
            block_key = normalise_key(line.key)
            block_indent = indent if block_key in SECRET_BLOCK_KEYS else None
        in_secret_block = block_key in SECRET_BLOCK_KEYS
        for key, value_text, is_child in _entries(line):
            normalised = normalise_key(key)
            if in_secret_block and is_child:
                declared.add(normalised)
            if in_secret_block and normalised in NON_SECRET_KEYS_IN_SECRET_BLOCK:
                continue
            if not in_secret_block and not is_secret_material_key(key):
                continue
            value = strip_scalar(value_text)
            if value in BLOCK_SCALAR_INDICATORS:
                findings.append(Finding(path, number, key, REASON_BLOCK_SCALAR))
                unreadable_region = True
                continue
            classification = classify_value(value)
            if classification == EMPTY:
                if is_child or not in_secret_block:
                    pending_secret_indent = indent
                    pending_secret_key = key
                if normalised in weak_default_keys:
                    findings.append(
                        Finding(path, number, key, REASON_EMPTY_WEAK_DEFAULT)
                    )
                continue
            if classification == WEAK:
                findings.append(Finding(path, number, key, REASON_WEAK_VALUE))
                unreadable_region = True
                continue
            if classification == MATERIAL:
                reason = (
                    REASON_BLOCK_NOT_PLACEHOLDER
                    if in_secret_block
                    else REASON_NOT_PLACEHOLDER
                )
                findings.append(Finding(path, number, key, reason))
                unreadable_region = True
                continue
            # A placeholder/reference is only safe when the scalar ends on this
            # line. A more-indented continuation changes the YAML value and must
            # therefore be refused on the following line.
            if is_child or not in_secret_block:
                pending_secret_indent = indent
                pending_secret_key = key
    # Rule 3: a key that is simply gone leaves no line to report, so it is reported
    # against the file. A removed secret block reports every key it should have held.
    findings.extend(
        Finding(path, 0, chart_key, REASON_MISSING_WEAK_DEFAULT)
        for normalised, chart_key in sorted(required_keys.items())
        if normalised not in declared
    )
    return findings


def scan_values_path(root: Path, relative: str) -> list[Finding]:
    """Scan one values file, resolving weak chart defaults from its own chart."""
    absolute = root / relative
    if not absolute.is_file():
        return []
    chart_dir = chart_dir_for(absolute)
    weak_keys = (
        weak_default_secret_keys(chart_dir) if chart_dir is not None else NO_KEYS
    )
    required = weak_keys if absolute.name == AUTHORITATIVE_VALUES_FILE else NO_KEYS
    text = absolute.read_text(encoding="utf-8", errors="replace")
    return scan_values_file(relative, text, weak_keys, required)
