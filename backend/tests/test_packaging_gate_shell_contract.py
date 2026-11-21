"""Every Helm packaging call site runs the secret-containment preflight first.

The scanners themselves are covered by ``test_secret_containment_contract.py`` and
``test_secret_containment_yaml_forms.py``, the tracked tree by
``test_release_values_secret_containment.py``. What is guarded here is the *wiring*: a packaging
path that skips the preflight publishes whatever is on disk, so the gate is only worth as much as
its placement, and its placement is only worth as much as the inventory that finds new call sites.

The inventory is therefore built from ``git ls-files`` rather than from a fixed directory list, and
it covers three kinds of call site:

* executable CI definitions — any tracked ``.github/**`` ``*.yml`` / ``*.yaml``, so a workflow saved
  with the other YAML suffix, a reusable workflow, or a composite action cannot package ungated;
* tracked shell scripts anywhere in the tree, not only ``scripts/*.sh``, so a nested or relocated
  packaging helper is found too;
* documented runbook commands — a fenced block in any tracked markdown that runs ``helm package``
  is a packaging path the moment somebody copies it, so it must carry both preflights. This is the
  one place where "documentation only" is not an exemption.

No deployment value is read, asserted on, or printed; these tests look at call ordering, shell
syntax and lint findings only.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGING_SCRIPT = REPO_ROOT / "scripts" / "local-build-push.sh"
PACKAGE_CHECK = "check_chart_package_inputs.py"
TRACKED_CHECK = "check_release_values_secrets.py"

requires_shellcheck = pytest.mark.skipif(shutil.which("shellcheck") is None, reason="needs shellcheck")
requires_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

PACKAGE_COMMAND = re.compile(r"helm package\b")
FENCED_BLOCK = re.compile(r"^```[^\n]*\n(?P<body>.*?)^```", re.DOTALL | re.MULTILINE)

# Reading a chart values file back into the job log. Everything here emits content; ``sed -i``
# rewrites in place and is excluded by the ``-i`` check at the call site below.
VALUES_FILE = r"values[A-Za-z0-9_.-]*\.ya?ml"
CONTENT_READER = re.compile(
    rf"\b(?P<command>cat|head|tail|less|more|od|xxd|base64|strings|awk|grep|yq|jq|sed)\b[^\n]*{VALUES_FILE}"
)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(entry for entry in result.stdout.split("\0") if entry)


def _executable_lines(path: Path) -> str:
    """The file without its comment lines.

    Both YAML and shell comment with a leading ``#``, and the gates themselves are commented with
    an explanation of what they guard. Ordering must be judged on what the file runs, not on prose
    that happens to name the packaging command.
    """
    source = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in source if not line.lstrip().startswith("#"))


def _is_executable_candidate(relative: str) -> bool:
    """True for a tracked path a packaging run could execute.

    Both halves are deliberately wider than the paths in use today: GitHub reads workflows under
    either YAML suffix and runs composite actions from anywhere under ``.github/``, and a packaging
    helper may be moved or nested at any depth instead of staying in ``scripts/``.
    """
    if relative.endswith(".sh"):
        return True
    return relative.startswith(".github/") and relative.endswith((".yml", ".yaml"))


def _executable_inventory() -> list[str]:
    """Every tracked file a packaging run could execute: CI definitions and shell scripts."""
    return [relative for relative in _tracked_files() if _is_executable_candidate(relative)]


def _packaging_call_sites() -> list[Path]:
    """Every executable file that invokes ``helm package``."""
    found = [
        REPO_ROOT / relative
        for relative in _executable_inventory()
        if PACKAGE_COMMAND.search(_executable_lines(REPO_ROOT / relative))
    ]
    assert found, "no packaging call site found; the inventory or the invocation spelling changed"
    return found


def _documented_packaging_commands() -> list[tuple[str, str]]:
    """Every fenced markdown block that runs ``helm package``, as (path, block body) pairs."""
    found: list[tuple[str, str]] = []
    for relative in _tracked_files():
        if not relative.endswith(".md"):
            continue
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        if "helm package" not in text:
            continue
        for block in FENCED_BLOCK.finditer(text):
            body = block.group("body")
            if PACKAGE_COMMAND.search(body):
                found.append((relative, body))
    assert found, "no documented packaging command found; deployment/helm/octryx/README.md carries it"
    return found


@pytest.mark.parametrize("call_site", _packaging_call_sites(), ids=lambda path: path.name)
def test_packaging_call_site_runs_the_package_input_check_before_packaging(call_site: Path) -> None:
    source = _executable_lines(call_site)
    checked = source.find(PACKAGE_CHECK)
    packaged = PACKAGE_COMMAND.search(source)
    assert packaged is not None
    assert checked != -1, f"{call_site.name} packages a chart without running {PACKAGE_CHECK}"
    assert checked < packaged.start(), f"{call_site.name} runs {PACKAGE_CHECK} after `helm package`"


@requires_bash
def test_packaging_script_is_syntactically_valid() -> None:
    result = subprocess.run(["bash", "-n", str(PACKAGING_SCRIPT)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


@requires_shellcheck
def test_packaging_script_has_no_shellcheck_findings() -> None:
    # Zero findings, no waiver and no inline disable: a lint gate that carries exceptions stops
    # being a gate. Fix the script instead of annotating it.
    result = subprocess.run(
        ["shellcheck", "-x", "--format=gcc", str(PACKAGING_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout or result.stderr
    assert "shellcheck disable" not in PACKAGING_SCRIPT.read_text(encoding="utf-8")


def test_packaging_script_aborts_when_a_preflight_fails() -> None:
    # `set -euo pipefail` is what turns a non-zero preflight into an abort; without it the script
    # would log the findings and package the chart anyway.
    source = _executable_lines(PACKAGING_SCRIPT)
    assert source.index("set -euo pipefail") < source.index(PACKAGE_CHECK)
    for line in source.splitlines():
        if PACKAGE_CHECK in line or TRACKED_CHECK in line:
            assert "||" not in line, f"preflight exit code swallowed: {line.strip()}"


@pytest.mark.parametrize(
    ("document", "block"),
    _documented_packaging_commands(),
    ids=[f"{relative}#{index}" for index, (relative, _) in enumerate(_documented_packaging_commands())],
)
def test_documented_packaging_command_runs_both_preflights_first(document: str, block: str) -> None:
    # A runbook block is copy-pasted verbatim, so it is a packaging path with no CI around it.
    # Both checks belong in it: the tracked check covers the checkout, the directory check covers
    # the chart path on disk, which is what `helm package` actually archives.
    packaged = PACKAGE_COMMAND.search(block)
    assert packaged is not None
    for check in (TRACKED_CHECK, PACKAGE_CHECK):
        position = block.find(check)
        assert position != -1, f"{document} documents `helm package` without {check}"
        assert position < packaged.start(), f"{document} documents {check} after `helm package`"


@pytest.mark.parametrize(
    "relative",
    [
        ".github/workflows/helm-oci-push.yml",
        ".github/workflows/publish-chart.yaml",
        ".github/actions/package-chart/action.yml",
        "scripts/local-build-push.sh",
        "scripts/release/package-chart.sh",
        "deployment/local/package-chart.sh",
    ],
)
def test_inventory_covers_every_place_an_executed_packaging_command_could_live(relative: str) -> None:
    """The gate is only as good as the search that finds new call sites, so the search is pinned."""
    assert _is_executable_candidate(relative)


@pytest.mark.parametrize(
    "relative",
    ["README.md", "backend/app/main.py", "deployment/helm/octryx/values.yaml", "deployment/helm/values.example.yaml"],
)
def test_inventory_stays_out_of_files_a_packaging_run_never_executes(relative: str) -> None:
    assert not _is_executable_candidate(relative)


def test_the_chart_readme_carries_the_documented_packaging_command() -> None:
    """The chart's README documents the manual packaging (with both checks first); it may not drop out."""
    documents = {relative for relative, _ in _documented_packaging_commands()}
    assert "deployment/helm/octryx/README.md" in documents


@pytest.mark.parametrize("call_site", _packaging_call_sites(), ids=lambda path: path.name)
def test_no_chart_values_content_is_printed_before_the_gates(call_site: Path) -> None:
    # A packaging run may rewrite the chart's values before packaging, so anything that reads those files back into
    # the log does it while the content is still unchecked. Logs are kept and shared, so the dump has to come after
    # the gates or not at all.
    source = _executable_lines(call_site)
    gate = min(source.index(TRACKED_CHECK), source.index(PACKAGE_CHECK))
    for match in CONTENT_READER.finditer(source):
        line = source[source.rfind("\n", 0, match.start()) + 1 : source.find("\n", match.start())]
        if match.group("command") == "sed" and re.search(r"\bsed\s+-i\b", line):
            continue
        assert match.start() > gate, f"chart values are read before the containment gates: {line.strip()}"
