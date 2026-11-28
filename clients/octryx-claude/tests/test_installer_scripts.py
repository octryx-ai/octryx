from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

import pytest

from tests.installer_scripts_support import BASE_URL, INSTALLER, KIT, _rendered_ps1

# Syntax PowerShell 7 added; Windows PowerShell 5.1 cannot parse it.
_PS7_ONLY = {
    "null-coalescing": re.compile(r"\?\?"),
    "null-conditional member": re.compile(r"\?\.|\?\["),
    "pipeline chain": re.compile(r"(?<![|'\"])(&&|\|\|)(?!['\"])"),
    "ternary": re.compile(r"\)\s*\?\s*\S+\s*:\s"),
    "ForEach-Object -Parallel": re.compile(r"-Parallel\b"),
}


def _code_lines(script: str) -> list[str]:
    lines = []
    for line in script.splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"'[^']*'|\"[^\"]*\"", "''", line))
    return lines


@pytest.mark.skipif(shutil.which("curl") is None, reason="needs curl")
def test_install_sh_suite_against_fake_platform(tmp_path):
    env = {**os.environ, "OCTRYX_TEST_PYTHON": sys.executable, "TMPDIR": str(tmp_path)}
    done = subprocess.run(["bash", str(KIT / "tests" / "installer" / "install_sh_test.sh")], env=env,
                          capture_output=True, text=True, timeout=900, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "ALL PASSED" in done.stdout


def test_install_sh_is_bash_32_syntax_clean():
    done = subprocess.run(["/bin/bash", "-n", str(INSTALLER / "install.sh")], capture_output=True, text=True,
                          check=False)
    assert done.returncode == 0, done.stderr


def test_ps1_has_no_powershell_7_only_syntax():
    code = "\n".join(_code_lines(_rendered_ps1()))
    found = [name for name, pattern in _PS7_ONLY.items() if pattern.search(code)]
    assert found == []


def test_ps1_rendered_with_platform_url_and_workspace_only():
    script = _rendered_ps1("ws-1")
    assert f"$OctryxBaseUrl = '{BASE_URL}'" in script
    assert "$OctryxWorkspace = 'ws-1'" in script
    assert "@@OCTRYX_" not in script
    assert not re.search(r"(?i)(token|password|secret)\s*=", script)


def test_ps1_never_writes_claude_config():
    code = [line for line in (INSTALLER / "install.ps1").read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")]
    assert not [line for line in code if ".claude" in line]
