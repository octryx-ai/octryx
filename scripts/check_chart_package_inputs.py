#!/usr/bin/env python3
"""Preflight for the chart directory that is about to be packaged.

``helm package`` archives the directory as it exists on disk, so this check inspects
the real contents of the given chart path — including untracked and git-ignored
files — and fails on secret material or unexpected values files that ``.helmignore``
does not exclude. Run it immediately before ``helm package``.

Usage:
    python3 scripts/check_chart_package_inputs.py CHART_DIR [CHART_DIR ...]
    python3 scripts/check_chart_package_inputs.py CHART_DIR --allow-extra-file values.images.yaml

Files are never read back into the output: a finding reports path, line, key name and
a reason code only.

Exit code 0 means clean, 1 means findings, 2 means the check could not run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from secret_containment.package_scan import check_chart_directory  # noqa: E402
from secret_containment.report import report  # noqa: E402

GUIDANCE = (
    "Exclude machine-local files through the chart's .helmignore, or remove them from the\n"
    "chart directory before packaging. Extra generated values files must be passed with\n"
    "--allow-extra-file so the exception is visible in the packaging command."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chart_dirs", nargs="+", help="Chart directories to inspect before packaging")
    parser.add_argument(
        "--allow-extra-file",
        action="append",
        default=[],
        metavar="NAME",
        help="Chart-root file name that is expected in the package (repeatable)",
    )
    args = parser.parse_args(argv)

    allowed = frozenset(args.allow_extra_file)
    findings = []
    for chart_dir in args.chart_dirs:
        try:
            findings.extend(check_chart_directory(Path(chart_dir).resolve(), allowed))
        except ValueError as error:
            print(f"{parser.prog}: {error}", file=sys.stderr)
            return 2
    return report(findings, "Chart package inputs: no findings.", GUIDANCE)


if __name__ == "__main__":
    sys.exit(main())
