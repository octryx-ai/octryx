"""CI per-test reports read from each provider ("Canonical test ids").

GitHub's JUnit artifacts run end to end in the device rehearsal (``test_workflow_live_rehearsal_b_device``); here the
GitLab ``test_report`` and the Bitbucket Cloud Pipelines step reports are read in the provider's shapes, and the CI
status read records them as a test run keyed canonically.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.services.workflow_checks.test_ids import Resolver
from app.services.workflow_runs.platform.ci_tests import bitbucket_tests, from_cases
from app.services.workflow_runs.test_resolution import resolve_entry
from app.tools.bitbucket_impl import _bitbucket_cloud_ops as cloud_ops
from app.tools.connectors import ci_test_reports


@pytest.mark.asyncio
async def test_gitlab_returns_the_pipeline_test_report_cases(monkeypatch):
    calls = []

    async def http(method, url, **kwargs):
        calls.append(url)
        return {"test_suites": [{"name": "pytest", "test_cases": [
            {"status": "failed", "name": "test_half_up", "classname": "tests.test_totals",
             "file": "tests/test_totals.py", "system_output": "assert 2 == 3"},
            {"status": "success", "name": "test_zero", "classname": "tests.test_totals"}]}]}

    async def headers(_context):
        return {}

    monkeypatch.setattr(ci_test_reports, "_http_json", http)
    monkeypatch.setattr(ci_test_reports, "_gitlab_headers", headers)
    monkeypatch.setattr(ci_test_reports, "_gitlab_base_url", lambda _context: "https://gitlab.test/api/v4")
    cases = await ci_test_reports.gitlab_test_cases(object(), "group/pay", "77")
    assert calls == ["https://gitlab.test/api/v4/projects/group%2Fpay/pipelines/77/test_report"]
    entry = resolve_entry({"results": {}, **from_cases(cases).fields()}, Resolver(["tests/test_totals.py"]))
    assert {key: value["outcome"] for key, value in entry["results"].items()} == {
        "tests/test_totals.py::test_half_up": "failed", "tests/test_totals.py::test_zero": "passed"}
    assert entry["results"]["tests/test_totals.py::test_half_up"]["message"] == "assert 2 == 3"


@pytest.mark.asyncio
async def test_bitbucket_cloud_reads_each_pipelines_step_test_report(monkeypatch):
    paths = []

    async def cloud_request(_context, method, path, **kwargs):
        paths.append(path)
        if path.endswith("/steps/"):
            return {"values": [{"uuid": "{step-1}"}]}
        return {"values": [{"name": "test_half_up", "fully_qualified_name": "tests.test_totals.test_half_up",
                            "status": "FAILED"},
                           {"name": "test_zero", "fully_qualified_name": "tests.test_totals.test_zero",
                            "status": "SUCCESSFUL"}]}

    monkeypatch.setattr(cloud_ops, "cloud_request", cloud_request)
    assert cloud_ops.pipeline_number("https://bitbucket.org/acme/pay/pipelines/results/42") == "42"
    assert cloud_ops.pipeline_number("https://ci.example.test/job/1") == ""
    cases = await cloud_ops.pipeline_test_cases(object(), "acme", "pay", "42")
    assert paths[0].endswith("/pipelines/42/steps/") and "%7Bstep-1%7D/test_reports/test_cases" in paths[1]
    parsed = bitbucket_tests([{"state": "FAILED", "test_cases": cases}])
    entry = resolve_entry({"results": {}, **parsed.fields()}, Resolver(["tests/test_totals.py"]))
    assert {key: value["outcome"] for key, value in entry["results"].items()} == {
        "tests/test_totals.py::test_half_up": "failed", "tests/test_totals.py::test_zero": "passed"}


def test_only_bounded_junit_files_of_an_artifact_are_read():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("reports/report.xml", '<testsuite><testcase classname="a" name="b"/></testsuite>')
        bundle.writestr("reports/coverage.xml", "<coverage/>")
        bundle.writestr("notes.txt", "<testcase")
    reports = ci_test_reports._xml_files(buffer.getvalue(), "test-reports")
    assert [item["path"] for item in reports] == ["reports/report.xml"]
    assert ci_test_reports._xml_files(b"not a zip", "x") == []


@pytest.mark.asyncio
async def test_a_bitbucket_step_without_a_test_report_contributes_none_and_other_refusals_raise(monkeypatch):
    """Bitbucket Cloud answers 404 on ``test_cases`` of a step that reported no tests."""
    from app.tools.bitbucket_impl._bitbucket_cloud import CloudApiError

    failure = {"status": 404}

    async def cloud_request(_context, method, path, **kwargs):
        if path.endswith("/steps/"):
            return {"values": [{"uuid": "{lint}"}, {"uuid": "{test}"}]}
        if "%7Blint%7D" in path:
            raise CloudApiError(failure["status"], "Not found")
        return {"values": [{"name": "test_zero", "fully_qualified_name": "tests.test_totals.test_zero",
                            "status": "SUCCESSFUL"}]}

    monkeypatch.setattr(cloud_ops, "cloud_request", cloud_request)
    cases = await cloud_ops.pipeline_test_cases(object(), "acme", "pay", "6")
    assert [case["name"] for case in cases] == ["test_zero"]
    failure["status"] = 500
    with pytest.raises(CloudApiError):
        await cloud_ops.pipeline_test_cases(object(), "acme", "pay", "6")


@pytest.mark.asyncio
async def test_an_unreadable_test_report_never_hides_the_bitbucket_build_state(db, monkeypatch):
    from app.tools.bitbucket_impl._bitbucket_cloud import CloudApiError
    from app.tools.bitbucket_impl._bitbucket_delivery import GetBitbucketBuildStatuses
    from tests.test_bitbucket_cloud_tools import HEAD, _context

    async def statuses(_context, workspace, slug, commit):
        return [{"state": "SUCCESSFUL", "url": "https://bitbucket.org/acme/payments/pipelines/results/6",
                 "commit": commit}]

    async def refused(_context, workspace, slug, number):
        raise CloudApiError(503, "Service unavailable")

    monkeypatch.setattr(cloud_ops, "build_statuses", statuses)
    monkeypatch.setattr(cloud_ops, "pipeline_test_cases", refused)
    result = await GetBitbucketBuildStatuses().execute(
        {"project_key": "ACME", "repo_slug": "payments", "commit": HEAD, "include_test_reports": True},
        await _context(db))
    assert "error" not in result and [item["state"] for item in result["statuses"]] == ["SUCCESSFUL"]
    assert result["statuses"][0]["test_report_error"] == {"status_code": 503, "message": "Service unavailable"}
    assert "test_cases" not in result["statuses"][0]
