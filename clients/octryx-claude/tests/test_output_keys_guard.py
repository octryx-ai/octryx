"""Every key the command runners write into a job's results is command output (redacted on the device,
``output_redact.OUTPUT_KEYS``) or named here as none: a new output field fails here until it is classified."""

from __future__ import annotations

import ast
from pathlib import Path

from octryx_claude import output_redact

PRODUCERS = ("pipeline_commands", "red_on_base", "test_report")
OUTPUT = frozenset({"output_tail", "report_text", "junit_xml"})
NOT_OUTPUT = frozenset({"browser", "command", "exit_code", "failed_tests", "files", "flaky", "format", "junit_files",
                        "path", "ran", "reason", "rerun", "seconds", "skipped", "state", "tests"})


def _written_keys(module: str) -> set[str]:
    source = Path(output_redact.__file__).with_name(f"{module}.py").read_text(encoding="utf-8")
    keys: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Dict):
            keys |= {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
        if isinstance(node, ast.Assign):
            keys |= {target.slice.value for target in node.targets if isinstance(target, ast.Subscript)
                     and isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str)}
    return keys


def test_every_result_key_is_classified_and_every_output_key_is_redacted():
    written = set().union(*(_written_keys(module) for module in PRODUCERS))
    assert written - OUTPUT - NOT_OUTPUT == set(), "classify the new key: OUTPUT (redacted) or NOT_OUTPUT"
    assert OUTPUT <= output_redact.OUTPUT_KEYS
    assert not OUTPUT & NOT_OUTPUT
