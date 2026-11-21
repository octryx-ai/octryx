"""Deployment secret containment preflight.

Stdlib only, so the checks run from CI and from the packaging script with plain
``python3`` before any dependency install step.

Entry points:

* ``scripts/check_release_values_secrets.py`` — tracked repository material.
* ``scripts/check_chart_package_inputs.py`` — the exact chart directory that is
  about to be packaged, including untracked and git-ignored additions.
"""

from .contract import Finding, classify_value, normalise_key
from .env_scan import looks_like_secret_manifest, scan_env_file, scan_secret_manifest
from .file_kinds import (
    effective_name,
    is_env_file,
    is_values_file,
    scan_env_or_secret_path,
)
from .package_scan import check_chart_directory
from .tracked_scan import check_paths, tracked_files
from .values_scan import scan_values_file, scan_values_path, weak_default_secret_keys
from .yaml_lines import (
    KeyLine,
    RootFlowDocument,
    SequenceItem,
    flow_mapping_entries,
    is_template_expression,
    match_key_line,
    root_flow_document,
    sequence_item,
    strip_trailing_comment,
)

__all__ = [
    "Finding",
    "KeyLine",
    "RootFlowDocument",
    "SequenceItem",
    "check_chart_directory",
    "check_paths",
    "classify_value",
    "effective_name",
    "flow_mapping_entries",
    "is_env_file",
    "is_template_expression",
    "is_values_file",
    "looks_like_secret_manifest",
    "match_key_line",
    "normalise_key",
    "root_flow_document",
    "sequence_item",
    "scan_env_file",
    "scan_env_or_secret_path",
    "scan_secret_manifest",
    "scan_values_file",
    "scan_values_path",
    "strip_trailing_comment",
    "tracked_files",
    "weak_default_secret_keys",
]
