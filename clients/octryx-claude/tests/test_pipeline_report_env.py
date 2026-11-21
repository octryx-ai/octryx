"""The platform's per-test report through report_env runs a real `node --test` green and writes its JUnit, also when
the report's folder does not exist yet (rc1 node-bug 0d791e71: ENOENT on test-reports/, exit 7)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from octryx_claude.pipeline_commands import report_env_for

NODE_OPTIONS = ("--test-reporter=spec --test-reporter-destination=stdout --test-reporter=junit "
                "--test-reporter-destination={report}")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_a_real_node_run_with_the_report_env_is_green_and_writes_junit(tmp_path):
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "a.test.js").write_text(
        "import test from 'node:test';\nimport assert from 'node:assert';\n"
        "test('one plus one', () => assert.equal(1 + 1, 2));\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    report = tmp_path / "test-reports" / "pipeline-1.xml"  # the folder does not exist yet
    env = report_env_for({"PATH": str(Path(shutil.which("node")).parent)}, report, {"NODE_OPTIONS": NODE_OPTIONS})
    done = subprocess.run(["node", "--test", "test/"], cwd=tmp_path, env=env, capture_output=True, text=True,
                          timeout=60, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "✔ one plus one" in done.stdout  # the agent's and the pipeline's output stays the spec reporter's
    xml = report.read_text(encoding="utf-8")
    assert '<testcase name="one plus one"' in xml and "test/a.test.js" in xml
