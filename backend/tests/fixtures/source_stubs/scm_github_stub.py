"""A GitHub REST stub over local bare git repositories, for workflow-run acceptance (S9)."""

from __future__ import annotations

import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

from stub_http import split_target

REPOS_ROOT = Path("/nonexistent")
PULLS: dict[str, dict] = {}
RUNS: dict[str, list[dict]] = {}
ARTIFACTS: dict[int, dict] = {}  # artifact id → {"run_id", "name", "zip"}
_REPO = re.compile(r"^/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)(?P<rest>/.*)?$")


def configure(root: Path) -> None:
    global REPOS_ROOT
    REPOS_ROOT = Path(root)
    PULLS.clear()
    RUNS.clear()
    ARTIFACTS.clear()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "--git-dir", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def _sha(repo: Path, branch: str) -> str | None:
    try:
        return _git(repo, "rev-parse", f"refs/heads/{branch}")
    except subprocess.CalledProcessError:
        return None


def merge(owner: str, repo: str, number: int) -> dict:
    pull = PULLS[f"{owner}/{repo}#{number}"]
    pull.update(state="closed", merged=True)
    return pull


def report_run(owner: str, repo: str, *, name: str, head_sha: str, conclusion: str | None,
               artifacts: dict[str, dict[str, str]] | None = None) -> dict:
    run = {"id": 1000 + sum(len(items) for items in RUNS.values()), "name": name, "head_sha": head_sha,
           "status": "completed" if conclusion else "in_progress", "conclusion": conclusion,
           "head_branch": "", "html_url": f"https://scm.stub.test/{owner}/{repo}/actions"}
    RUNS.setdefault(f"{owner}/{repo}", []).insert(0, run)
    for artifact, files in (artifacts or {}).items():
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            for path, content in files.items():
                bundle.writestr(path, content)
        ARTIFACTS[5000 + len(ARTIFACTS)] = {"run_id": run["id"], "name": artifact, "zip": buffer.getvalue()}
    return run


def handle(method: str, target: str, authorization: str | None,
           body: bytes | None = None) -> tuple[int, dict | bytes]:
    del authorization
    path, _query = split_target(target)
    path = path.removeprefix("/api/v3")
    match = _REPO.match(path)
    if match is None:
        return 404, {"message": "Not Found"}
    full = f"{match['owner']}/{match['repo']}"
    repo = REPOS_ROOT / match["owner"] / f"{match['repo']}.git"
    if not repo.exists():
        return 404, {"message": "Not Found"}
    rest = match["rest"] or ""
    data = json.loads(body or b"{}") if body else {}
    if method == "GET" and not rest:
        return 200, {"full_name": full, "default_branch": "main"}
    if method == "GET" and rest.startswith("/git/ref/heads/"):
        sha = _sha(repo, rest.removeprefix("/git/ref/heads/"))
        return (200, {"object": {"sha": sha}}) if sha else (404, {"message": "Not Found"})
    if method == "POST" and rest == "/git/refs":
        if _sha(repo, str(data["ref"]).removeprefix("refs/heads/")):
            return 422, {"message": "Reference already exists"}  # as GitHub answers: never overwritten
        _git(repo, "update-ref", str(data["ref"]), str(data["sha"]))
        return 201, {"ref": data["ref"], "object": {"sha": data["sha"]}}
    if method == "POST" and rest == "/pulls":
        if _sha(repo, str(data.get("head"))) is None:
            return 422, {"message": "head branch does not exist"}
        number = 1 + sum(1 for key in PULLS if key.startswith(full + "#"))
        pull = {"number": number, "title": data.get("title"), "state": "open", "merged": False,
                "head": {"ref": data.get("head")}, "base": {"ref": data.get("base")}, "requested_reviewers": [],
                "html_url": f"https://scm.stub.test/{full}/pull/{number}", "user": {"login": "octryx"}}
        PULLS[f"{full}#{number}"] = pull
        return 201, pull
    if method == "GET" and rest == "/actions/runs":
        runs = RUNS.get(full, [])
        return 200, {"total_count": len(runs), "workflow_runs": runs}
    jobs = re.match(r"^/actions/runs/(?P<id>\d+)/jobs$", rest)
    if method == "GET" and jobs:
        found = [{"id": item["id"], "name": item["name"], "status": item["status"], "conclusion": item["conclusion"]}
                 for item in RUNS.get(full, []) if item["id"] == int(jobs["id"])]
        return 200, {"total_count": len(found), "jobs": found}
    listed = re.match(r"^/actions/runs/(?P<id>\d+)/artifacts$", rest)
    if method == "GET" and listed:
        artifacts = [{"id": key, "name": item["name"], "size_in_bytes": len(item["zip"]), "expired": False}
                     for key, item in ARTIFACTS.items() if item["run_id"] == int(listed["id"])]
        return 200, {"total_count": len(artifacts), "artifacts": artifacts}
    download = re.match(r"^/actions/artifacts/(?P<id>\d+)/zip$", rest)
    if method == "GET" and download and int(download["id"]) in ARTIFACTS:
        return 200, ARTIFACTS[int(download["id"])]["zip"]
    pull_match = re.match(r"^/pulls/(?P<n>\d+)(?P<sub>/requested_reviewers)?$", rest)
    if pull_match and f"{full}#{pull_match['n']}" in PULLS:
        pull = PULLS[f"{full}#{pull_match['n']}"]
        if pull_match["sub"] and method == "POST":
            pull["requested_reviewers"] = [{"login": name} for name in data.get("reviewers") or []]
            return 201, pull
        if method == "GET":
            return 200, pull
    return 404, {"message": "Not Found"}
