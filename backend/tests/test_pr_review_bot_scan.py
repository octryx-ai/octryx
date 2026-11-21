"""PR review bot, the tool runner's findings: scanners report SARIF, a secret is never quoted, a linter only counts
on changed lines, a result outside the change is dropped."""

from __future__ import annotations

import json

from app.services.pr_review_bot.actions import with_caller_findings
from app.services.pr_review_bot.diff_lines import parse_diff
from app.services.pr_review_bot.render import build_post
from app.services.pr_review_bot.scan_findings import MAX_FINDINGS, changed_lines, scan_findings, to_facts

SECRET = ("AKIAAB" + "CDEFGHIJKLMNOP")
ROOT = "/tmp/octryx-scan-1"


def _sarif(driver: str, results: list[dict], rules: list[dict] | None = None) -> dict:
    return {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": driver, "rules": rules or []}},
                                          "results": results}]}


def _result(rule: str, path: str, line: int, text: str = "", level: str | None = None, snippet: str = "") -> dict:
    region = {"startLine": line, **({"snippet": {"text": snippet}} if snippet else {})}
    return {"ruleId": rule, **({"level": level} if level else {}), "message": {"text": text},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": path}, "region": region}}]}


GITLEAKS = ({"id": "gitleaks", "kind": "secrets"}, _sarif("gitleaks", [
    _result("aws-access-token", f"file://{ROOT}/pay/config.py", 3, f"aws-access-token has detected secret {SECRET}",
            snippet=f'KEY = "{SECRET}"')], [{"id": "aws-access-token",
                                             "shortDescription": {"text": "AWS access token"}}]))
OPENGREP = ({"id": "opengrep", "kind": "sast", "severity_map": {"error": "high"}}, _sarif("opengrep", [
    _result("python.lang.security.audit.eval", "pay/report.py", 40, "Detected eval() on user input.", "error"),
    _result("python.lang.security.audit.eval", "pay/untouched.py", 7, "Detected eval().", "error")]))
RUFF = ({"id": "ruff", "kind": "lint"}, _sarif("ruff", [
    _result("F401", "pay/report.py", 2, "`os` imported but unused", "error"),
    _result("E501", "pay/report.py", 90, "Line too long", "error")]))
CHANGED = {"pay/config.py": {3}, "pay/report.py": {2, 40}}


def test_scanners_become_findings_secrets_never_quoted():
    result = scan_findings([GITLEAKS, OPENGREP, RUFF], root=ROOT, changed=CHANGED)
    rows = [(f["id"], f["severity"], f["file"], f["line"], f["tool"], f["rule"]) for f in result.findings]
    assert rows == [("S1", "high", "pay/config.py", 3, "gitleaks", "aws-access-token"),
                    ("S2", "high", "pay/report.py", 40, "opengrep", "python.lang.security.audit.eval"),
                    ("S3", "medium", "pay/report.py", 2, "ruff", "F401")]  # a linter never above medium
    assert SECRET not in repr(result.findings) and "AWS access token" not in result.findings[0]["fix"]
    assert "rotate it" in result.findings[0]["fix"]
    assert result.findings[2]["fix"] == "ruff F401: `os` imported but unused"


def test_unchanged_lines_and_files_are_not_this_pull_requests_findings():
    result = scan_findings([OPENGREP, RUFF], root=ROOT, changed={"pay/report.py": {5}})
    assert [(f["file"], f["line"]) for f in result.findings] == [("pay/report.py", 40)]  # SAST: the whole file


def test_the_same_place_and_rule_once_and_a_bound():
    many = ({"id": "ruff", "kind": "lint"}, _sarif("ruff", [_result("E1", "a.py", n, "x", "warning")
                                                             for n in range(1, 50)]))
    result = scan_findings([many, many], root=ROOT, changed={"a.py": set(range(1, 50))})
    assert len(result.findings) == MAX_FINDINGS and result.dropped == 49 - MAX_FINDINGS


DIFF = """diff --git a/pay/config.py b/pay/config.py
--- a/pay/config.py
+++ b/pay/config.py
@@ -1,3 +1,4 @@
 import os
 NAME = "pay"
+KEY = "x"
 DEBUG = False
diff --git a/pay/gone.py b/pay/gone.py
deleted file mode 100644
--- a/pay/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-A = 1
"""


def test_a_secret_blocks_a_passing_review_and_the_post_names_the_scanners_never_the_secret():
    files = parse_diff(DIFF)
    assert changed_lines(files) == {"pay/config.py": {3}}  # added lines only; a deleted file is not scanned
    scan = to_facts(scan_findings([GITLEAKS], root=ROOT, changed=changed_lines(files)))
    scan["notes"] = ["opengrep not available on the device"]
    review = with_caller_findings({"verdict": "pass", "summary": "Fine.", "findings": []}, scan["findings"])
    post = build_post(review, files, provider="github", facts={
        "sha": "a" * 40, "scan": {key: scan[key] for key in ("tools", "dropped", "notes")}})
    assert post.state == "failure" and "Blocking (secret scan):** 1" in post.summary
    assert "scanned with gitleaks" in post.summary and "opengrep not available" in post.summary
    assert SECRET not in post.summary + "".join(comment.body for comment in post.comments)


def test_the_scanners_are_data_chosen_per_change_with_cleared_rule_sets_only():
    from app.services.pr_review_bot import scanners

    ids = [entry["id"] for entry in scanners.selected(["pay/report.py"])]
    assert ids == ["gitleaks", "opengrep"]  # no manifest changed: no dependency scan
    assert "osv-scanner" in [entry["id"] for entry in scanners.selected(["web/package-lock.json"])]
    assert scanners.selected([]) == []
    opengrep = next(entry for entry in scanners.scanners() if entry["id"] == "opengrep")
    assert scanners.command(opengrep, root="/t/files", report="/t/o.sarif", rules="/t/rules")[-5:] == [
        "--config", "/t/rules", "--sarif-output", "/t/o.sarif", "/t/files"]
    files, notes = scanners.rule_entries(opengrep)
    assert [name for name, _ in files] == ["octryx/octryx.yaml"] and notes == []
    registry = {**opengrep, "rule_sources": [{"name": "registry", "path": "pr_review_bot/scan_rules",
                                              "license": "Semgrep Rules License v1.0"}]}
    assert scanners.rule_entries(registry) == ([], [
        "rule set registry not shipped: license 'Semgrep Rules License v1.0' not cleared for Octryx"])
    stacks = {"general": {"scanners": [opengrep]},
              "stacks": {"python": {"scanners": [{**opengrep, "args": ["x"]}]}}}
    assert [entry["args"] for entry in scanners.scanners(stacks)] == [["x"]]  # the same id replaces


async def test_the_scan_runs_as_a_tool_job_on_a_seat_device_and_its_reports_become_findings(db, tmp_path, monkeypatch):
    import subprocess

    from app.models import WorkflowRun
    from app.services.devices import tool_jobs
    from app.services.pr_review_bot import scan_job
    from tests.pr_review_bot_flow_support import _workspace

    monkeypatch.setenv("OCTRYX_DEVICE_ARCHIVE_DIR", str(tmp_path / "store"))
    repo = tmp_path / "repo"
    (repo / "pay").mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@example.invalid"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "pay" / "config.py").write_text('import os\nNAME = "pay"\nKEY = "x"\nDEBUG = False\n')
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c"], check=True)
    project_id, _record, _hook = await _workspace(db)
    run = WorkflowRun(project_id=project_id, workflow_kind="phased", workflow_key="pr-review-bot", title="r",
                      requested_by=None, repository="github:acme/pay", branch="b", context={})

    async def seats(db_, run_):
        return ["dev-1"]

    monkeypatch.setattr(scan_job, "_candidates", seats)
    offered = await scan_job.offer_scan(db, run, root=str(repo), head="HEAD", diff=DIFF)
    assert [entry["id"] for entry in offered["scanners"]] == ["gitleaks", "opengrep"]
    assert await scan_job.read_scan(db, offered) == {"findings": [], "tools": [], "dropped": 0,
                                                    "notes": ["scan still running"]}

    class Device:
        device_id, tools, sent = "dev-1", {"gitleaks": "8.30.1"}, []

        async def send(self, kind, body):
            self.sent.append(body)

    device = Device()
    assert await tool_jobs.deliver(db, device) == 1  # needs nothing: opengrep's absence is a step status
    (body,) = device.sent
    assert [archive["name"] for archive in body["archives"]] == ["files", "rules"]
    assert body["steps"][0]["args"][-1] == "{archive:files}" and "{archive:rules}" in body["steps"][1]["args"]
    gitleaks = GITLEAKS[1]["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    gitleaks["artifactLocation"]["uri"] = "/var/tmp/octryx-tool-job-1/files/pay/config.py"
    await tool_jobs.apply_message(db, "dev-1", "tool_job_result", {"job_id": offered["job_id"], "steps": [
        {"id": "gitleaks", "status": "ok", "exit": 0, "files": {"gitleaks.sarif": json.dumps(GITLEAKS[1])}},
        {"id": "opengrep", "status": "missing", "exit": None}]})
    scan = await scan_job.read_scan(db, offered)
    assert [(item["id"], item["file"], item["kind"]) for item in scan["findings"]] == [
        ("S1", "pay/config.py", "secrets")]
    assert scan["tools"] == ["gitleaks"] and scan["notes"] == ["opengrep not available on the device"]
    assert SECRET not in json.dumps(scan)
