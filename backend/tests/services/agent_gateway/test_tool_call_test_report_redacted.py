"""The JUnit report the launcher attaches to a Bash test call is stored on the tool call: a test that prints a secret
into its report never keeps it there."""

from __future__ import annotations

from app.services.agent_gateway.tool_execution import test_report as report_of


def test_a_secret_in_a_junit_report_is_redacted_before_it_is_stored():
    secret = "ghp_" + "Q1w2E3r4T5y6U7i8O9p0A1s2D3f4G5h6J7k8"
    xml = (f'<testsuite><testcase classname="tests.test_api" name="test_login"><system-out>'
           f'Authorization: Bearer {secret}</system-out></testcase></testsuite>')
    stored = report_of("Bash", {"workflow_run_facts": {"test_report": {"path": "r.xml", "junit_xml": xml}}})
    assert stored is not None and secret not in stored["junit_xml"]
    assert '<testcase classname="tests.test_api" name="test_login">' in stored["junit_xml"], "the results stay"
