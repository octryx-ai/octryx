"""Per-test reports a CI pipeline published ("Canonical test ids")."""

from __future__ import annotations

import io
import re
import zipfile
from urllib.parse import quote

from ...services.outbound_egress import CONNECTION_GITHUB, CONNECTION_GITLAB
from ..context import ToolContext
from .common import _http_json, _http_response, _string
from .github import _github_base_url, _github_headers
from .gitlab import _gitlab_base_url, _gitlab_headers

MAX_ARTIFACT_BYTES = 5_000_000
MAX_REPORT_BYTES = 1_000_000
MAX_TOTAL_REPORT_BYTES = 2_000_000
MAX_REPORT_FILES = 20
MAX_CASES = 2000
_REPORT_ARTIFACT = re.compile(r"junit|test[-_ ]?(?:report|result)s?", re.IGNORECASE)


def _xml_files(archive: bytes, artifact: str) -> list[dict[str, str]]:
    reports: list[dict[str, str]] = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            for info in bundle.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".xml") or info.file_size > MAX_REPORT_BYTES:
                    continue
                if total + info.file_size > MAX_TOTAL_REPORT_BYTES or len(reports) >= MAX_REPORT_FILES:
                    break
                text = bundle.read(info).decode("utf-8", errors="replace")
                if "<testcase" in text:
                    total += info.file_size
                    reports.append({"artifact": artifact, "path": info.filename, "junit_xml": text})
    except zipfile.BadZipFile:
        return []
    return reports


async def github_junit_reports(context: ToolContext, owner: str, repo: str, run_id: str,
                               artifact: str = "") -> list[dict[str, str]]:
    base = f"{_github_base_url(context)}/repos/{owner}/{repo}/actions"
    headers = await _github_headers(context)
    listed = await _http_json("GET", f"{base}/runs/{quote(run_id, safe='')}/artifacts", connection=CONNECTION_GITHUB,
                              headers=headers, params={"per_page": 50})
    chosen = [item for item in listed.get("artifacts") or []
              if not item.get("expired") and int(item.get("size_in_bytes") or 0) <= MAX_ARTIFACT_BYTES
              and (str(item.get("name") or "") == artifact if artifact
                   else _REPORT_ARTIFACT.search(str(item.get("name") or "")))]
    reports: list[dict[str, str]] = []
    for item in chosen[:5]:
        response = await _http_response("GET", f"{base}/artifacts/{quote(str(item.get('id')), safe='')}/zip",
                                        connection=CONNECTION_GITHUB, headers=headers)
        if response.status_code < 400 and len(response.content) <= MAX_ARTIFACT_BYTES:
            reports += _xml_files(response.content, str(item.get("name") or ""))
    return reports[:MAX_REPORT_FILES]


async def gitlab_test_cases(context: ToolContext, project: str, pipeline_id: str) -> list[dict[str, str]]:
    report = await _http_json(
        "GET", f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/pipelines/"
               f"{quote(pipeline_id, safe='')}/test_report", connection=CONNECTION_GITLAB,
        headers=await _gitlab_headers(context))
    cases: list[dict[str, str]] = []
    for suite in report.get("test_suites") or []:
        for case in (suite or {}).get("test_cases") or []:
            cases.append({"classname": _string(case.get("classname")), "name": _string(case.get("name")),
                          "file": _string(case.get("file")), "status": _string(case.get("status")),
                          "message": _string(case.get("system_output"))[:500]})
            if len(cases) >= MAX_CASES:
                return cases
    return cases


__all__ = ["github_junit_reports", "gitlab_test_cases"]
