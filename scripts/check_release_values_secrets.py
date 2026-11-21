#!/usr/bin/env python3
"""Preflight that keeps deployment secret material out of tracked source.

Covers, over tracked files only (``git ls-files``):

* ``*.local.yaml`` / ``*.local.yml`` — machine-local secret input, never tracked.
* Helm release values files — secret-bearing keys must hold an explicit placeholder,
  and an empty key is rejected when the chart substitutes a weak default for it.
* Deployment env templates and Kubernetes Secret manifests (``kind: Secret``, detected
  by content, so a manifest named ``secrets.env`` is covered too).

A finding reports the file, the line, the key name, and a reason code. Key names are
part of the deployment schema; values are not. Do not extend these checks to emit
value text, lengths, or character classes.

Usage:
    python3 scripts/check_release_values_secrets.py             # tracked files
    python3 scripts/check_release_values_secrets.py FILE...     # explicit files
    python3 scripts/check_release_values_secrets.py --root DIR  # other repo root

Exit code 0 means clean, 1 means findings, 2 means the check could not run.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from secret_containment.report import report  # noqa: E402
from secret_containment.tracked_scan import check_paths, tracked_files  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="Repository root to check (default: current directory)")
    parser.add_argument("paths", nargs="*", help="Repository-relative paths to check instead of all tracked files")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.paths:
        paths = args.paths
    else:
        try:
            paths = tracked_files(root)
        except (OSError, subprocess.CalledProcessError):
            print(f"{parser.prog}: cannot list tracked files in {root}", file=sys.stderr)
            return 2

    return report(check_paths(root, paths), "Tracked deployment secret containment: no findings.")


if __name__ == "__main__":
    sys.exit(main())
