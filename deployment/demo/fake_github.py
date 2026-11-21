"""Fake GitHub for the demo (compose profile ``demo``, service ``demo-git``): the REST calls a run makes, plus git.

A team-delivery run talks to its repository through the GitHub connection (``backend/app/tools/connectors/
github*.py``): default branch, branch sha, create branch (``POST git/refs``), clone/push over
``<host>/<owner>/<repo>.git``, pull request create/get/update, requested reviewers, ``GET /user``. This fake serves
exactly that over bare repositories under ``--root`` (default ./remotes, as <root>/<owner>/<repo>.git),
so branches and pushes are real git and pull requests are JSON records.

Run:   python fake_github.py [--host 0.0.0.0] [--port 8434] [--root DIR] [--public-url URL]
Seed:  POST /_fake/repos {"owner": "demo", "repo": "demo-shop", "files": {"README.md": "..."}}  (idempotent)
Read:  GET /_fake/pulls  (every PR with its comments, reviews and statuses); GET /repos/<o>/<r>/git/trees/<ref>
View:  GET /<owner>/<repo>/pull/<n>  a read-only HTML page of one pull request (the ``html_url`` every link names):
       title, description, diff stat and the diff (folded), conversation comments, reviews with their inline comments
       and the commit statuses. No script, no form: it only shows what this fake holds.

The PR review bot also gets what it calls: conversation comments (list, post, edit; repository-wide
``issues/comments?since=``), reviews with inline comments and their replies (``pulls/comments?since=``), commit
statuses (post, list) and check runs (none), a commenter's permission (``admin``) and the GraphQL review threads
(none, so a resolve is a no-op).

The connection points at ``http://127.0.0.1:8434/api/v3`` (GitHub Enterprise form, so the clone URL is
``http://127.0.0.1:8434/<owner>/<repo>.git``); the platform reaches it through the loopback exemption
``OCTRYX_SOURCE_SYNC_ALLOW_LOOPBACK_HOSTS=127.0.0.1:8434``. In compose it listens on every address of the
API's network namespace (``--host 0.0.0.0``), so the same URL works inside it and, published on the host's
127.0.0.1, for a local device; ``--public-url`` names that URL in every link it answers. Tokens are accepted as they
come: a local demo only, nothing here is protected and nothing is a secret.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

LOCK = threading.RLock()
BOT = {"login": "demo-bot", "id": 1, "type": "User"}
_REPO = r"/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    """Bare repositories on disk and pull requests in a JSON file next to them."""

    def __init__(self, root: Path, base_url: str) -> None:
        self.root = root
        self.base_url = base_url
        self.state_path = root / "fake-github-state.json"
        root.mkdir(parents=True, exist_ok=True)
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {"pulls": []}

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, sort_keys=True))
        os.replace(tmp, self.state_path)

    def repo_dir(self, owner: str, repo: str) -> Path:
        return self.root / owner / f"{repo.removesuffix('.git')}.git"

    def git(self, owner: str, repo: str, *args: str, check: bool = True) -> str:
        done = subprocess.run(["git", "--git-dir", str(self.repo_dir(owner, repo)), *args], capture_output=True,
                              text=True, check=False)
        if check and done.returncode != 0:
            raise RuntimeError(done.stderr.strip()[:300])
        return done.stdout.strip() if done.returncode == 0 else ""

    def exists(self, owner: str, repo: str) -> bool:
        return (self.repo_dir(owner, repo) / "HEAD").exists()

    def default_branch(self, owner: str, repo: str) -> str:
        ref = self.git(owner, repo, "symbolic-ref", "HEAD", check=False)
        return ref.removeprefix("refs/heads/") or "main"

    def sha(self, owner: str, repo: str, branch: str) -> str:
        return self.git(owner, repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}", check=False)

    def create_repo(self, owner: str, repo: str, files: dict[str, str]) -> dict[str, Any]:
        """A bare repository with one commit on ``main`` holding ``files``; an existing one stays as it is."""
        target = self.repo_dir(owner, repo)
        if self.exists(owner, repo):
            return {"created": False, "path": str(target)}
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(target)], check=True)
        self.git(owner, repo, "config", "http.receivepack", "true")
        work = target.parent / f".seed-{repo}"
        subprocess.run(["rm", "-rf", str(work)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
        for name, text in (files or {"README.md": f"# {repo}\n"}).items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        env = {**os.environ, "GIT_AUTHOR_NAME": "demo", "GIT_AUTHOR_EMAIL": "demo@localhost.invalid",
               "GIT_COMMITTER_NAME": "demo", "GIT_COMMITTER_EMAIL": "demo@localhost.invalid"}
        for command in (["git", "add", "-A"], ["git", "commit", "-q", "-m", "Initial commit"],
                        ["git", "push", "-q", str(target), "main"]):
            subprocess.run(command, cwd=work, env=env, check=True)
        subprocess.run(["rm", "-rf", str(work)], check=True)
        return {"created": True, "path": str(target)}

    def repo_json(self, owner: str, repo: str) -> dict[str, Any]:
        web = self.base_url.removesuffix("/api/v3")
        return {"id": abs(hash((owner, repo))) % 10**8, "name": repo, "full_name": f"{owner}/{repo}",
                "owner": {"login": owner}, "private": True, "default_branch": self.default_branch(owner, repo),
                "html_url": f"{web}/{owner}/{repo}", "clone_url": f"{web}/{owner}/{repo}.git",
                "permissions": {"admin": True, "push": True, "pull": True}}

    def activity(self, pull: dict[str, Any]) -> dict[str, Any]:
        """What the review bot left on the pull request: comments, reviews and their inline comments, statuses."""
        def of(kind: str, key: str, value: Any) -> list[dict[str, Any]]:
            return [row for row in self.state.get(kind, [])
                    if (row["owner"], row["repo"], row.get(key)) == (pull["owner"], pull["repo"], value)]

        sha = self.sha(pull["owner"], pull["repo"], pull["head"])
        return {"comments": of("comments", "issue", pull["number"]), "reviews": of("reviews", "pull", pull["number"]),
                "review_comments": of("review_comments", "pull", pull["number"]),
                "statuses": of("statuses", "sha", sha)}

    def pull_json(self, pull: dict[str, Any]) -> dict[str, Any]:
        owner, repo = pull["owner"], pull["repo"]
        web = self.base_url.removesuffix("/api/v3")
        return {"number": pull["number"], "id": pull["number"], "state": pull["state"], "title": pull["title"],
                "body": pull["body"], "draft": False, "merged": False, "user": BOT,
                "head": {"ref": pull["head"], "sha": self.sha(owner, repo, pull["head"]), "label": pull["head"],
                         "repo": {"full_name": f"{owner}/{repo}"}},
                "base": {"ref": pull["base"], "sha": self.sha(owner, repo, pull["base"]), "label": pull["base"],
                         "repo": {"full_name": f"{owner}/{repo}"}},
                "html_url": f"{web}/{owner}/{repo}/pull/{pull['number']}",
                "url": f"{self.base_url}/repos/{owner}/{repo}/pulls/{pull['number']}",
                "requested_reviewers": [{"login": name} for name in pull.get("reviewers", [])],
                "created_at": pull["created_at"], "updated_at": pull["updated_at"]}


def handle_api(store: Store, method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
    if path in ("/user", "/api/v3/user"):
        return 200, BOT
    path = path.removeprefix("/api/v3")
    if path == "/_fake/repos" and method == "POST":
        return 201, store.create_repo(body["owner"], body["repo"], body.get("files") or {})
    if path == "/_fake/pulls":
        return 200, [store.pull_json(pull) | {"repository": f"{pull['owner']}/{pull['repo']}"} | store.activity(pull)
                     for pull in store.state["pulls"]]
    if path in ("/graphql", "/api/graphql") and method == "POST":
        # The review bot resolves a thread through GraphQL: no thread is known here, so a resolve is a no-op.
        return 200, {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}}
    match = re.match(_REPO + r"(?P<rest>/.*)?$", path)
    if not match:
        return 404, {"message": "Not Found"}
    owner, repo, rest = match["owner"], match["repo"], match["rest"] or ""
    if not store.exists(owner, repo):
        return 404, {"message": "Not Found"}
    if rest == "" and method == "GET":
        return 200, store.repo_json(owner, repo)
    if (ref := re.fullmatch(r"/git/ref/heads/(.+)", rest)) and method == "GET":
        sha = store.sha(owner, repo, unquote(ref[1]))
        if not sha:
            return 404, {"message": "Not Found"}
        return 200, {"ref": f"refs/heads/{unquote(ref[1])}", "object": {"sha": sha, "type": "commit"}}
    if rest == "/git/refs" and method == "POST":
        name, sha = str(body.get("ref") or ""), str(body.get("sha") or "")
        if not name.startswith("refs/heads/") or not sha:
            return 422, {"message": "Invalid request"}
        if store.sha(owner, repo, name.removeprefix("refs/heads/")):
            return 422, {"message": "Reference already exists"}
        store.git(owner, repo, "update-ref", name, sha)
        return 201, {"ref": name, "object": {"sha": sha, "type": "commit"}}
    if rest == "/branches" and method == "GET":
        refs = store.git(owner, repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
        return 200, [{"name": line.split()[0], "commit": {"sha": line.split()[1]}, "protected": False}
                     for line in refs.splitlines() if line.strip()]
    if (content := re.fullmatch(r"/contents/(.+)", rest)) and method == "GET":
        ref = (query.get("ref") or [store.default_branch(owner, repo)])[0]
        text = store.git(owner, repo, "show", f"{ref}:{unquote(content[1])}", check=False)
        if not text:
            return 404, {"message": "Not Found"}
        return 200, {"type": "file", "path": unquote(content[1]), "encoding": "base64",
                     "content": base64.b64encode(text.encode()).decode()}
    if (tree := re.fullmatch(r"/git/trees/(.+)", rest)) and method == "GET":
        # The files of a branch or commit (GitHub's recursive tree, blobs only): the platform's repository check
        # lists every .octryx/environment.json of a repository through it.
        ref = unquote(tree[1])
        sha = store.sha(owner, repo, ref) or ref
        listing = store.git(owner, repo, "ls-tree", "-r", "--name-only", sha, check=False)
        if not listing:
            return 404, {"message": "Not Found"}
        return 200, {"sha": sha, "truncated": False,
                     "tree": [{"path": name, "type": "blob", "mode": "100644"} for name in listing.splitlines() if name]}
    if rest == "/actions/runs":
        return 200, {"total_count": 0, "workflow_runs": []}
    reviewed = handle_review_bot(store, method, owner, repo, rest, query, body)
    if reviewed is not None:
        return reviewed
    return handle_pulls(store, method, owner, repo, rest, query, body)


def _page(items: list[dict[str, Any]], query: dict[str, list[str]]) -> list[dict[str, Any]]:
    """GitHub's ``per_page`` / ``page``: the bot reads lists page by page until one is short."""
    size = max(1, min(int((query.get("per_page") or ["30"])[0]), 100))
    page = max(1, int((query.get("page") or ["1"])[0]))
    return items[(page - 1) * size:page * size]


def _since(items: list[dict[str, Any]], query: dict[str, list[str]]) -> list[dict[str, Any]]:
    since = (query.get("since") or [""])[0]
    return [item for item in items if not since or item["updated_at"] >= since]


def _record(store: Store, kind: str, owner: str, repo: str, **fields: Any) -> dict[str, Any]:
    rows = store.state.setdefault(kind, [])
    row = {"id": len(rows) + 1, "owner": owner, "repo": repo, "user": BOT, "created_at": now(), "updated_at": now(),
           **fields}
    rows.append(row)
    store.save()
    return row


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in ("owner", "repo")}


def handle_review_bot(store: Store, method: str, owner: str, repo: str, rest: str, query: dict[str, list[str]],
                      body: Any) -> tuple[int, Any] | None:
    """The calls of the PR review bot; ``None`` for anything else."""
    body = body if isinstance(body, dict) else {}

    def mine(kind: str) -> list[dict[str, Any]]:
        return [row for row in store.state.get(kind, []) if (row["owner"], row["repo"]) == (owner, repo)]

    if (issue := re.fullmatch(r"/issues/(\d+)/comments", rest)):
        if method == "POST":
            return 201, _public(_record(store, "comments", owner, repo, issue=int(issue[1]),
                                        body=str(body.get("body") or "")))
        return 200, _page([_public(row) for row in mine("comments") if row["issue"] == int(issue[1])], query)
    if rest == "/issues/comments" and method == "GET":
        web = store.base_url.removesuffix("/api/v3")
        api = f"{store.base_url}/repos/{owner}/{repo}"
        return 200, _page([{**_public(row), "issue_url": f"{api}/issues/{row['issue']}",
                            "html_url": f"{web}/{owner}/{repo}/pull/{row['issue']}#issuecomment-{row['id']}"}
                           for row in _since(mine("comments"), query)], query)
    if (edit := re.fullmatch(r"/issues/comments/(\d+)", rest)) and method == "PATCH":
        row = next((item for item in mine("comments") if item["id"] == int(edit[1])), None)
        if row is None:
            return 404, {"message": "Not Found"}
        row.update(body=str(body.get("body") or ""), updated_at=now())
        store.save()
        return 200, _public(row)
    if (reviews := re.fullmatch(r"/pulls/(\d+)/reviews", rest)) and method == "POST":
        review = _record(store, "reviews", owner, repo, pull=int(reviews[1]), state="COMMENTED",
                         commit_id=str(body.get("commit_id") or ""), body=str(body.get("body") or ""))
        for comment in body.get("comments") or []:
            _record(store, "review_comments", owner, repo, pull=int(reviews[1]), review=review["id"],
                    path=str(comment.get("path") or ""), line=comment.get("line"), body=str(comment.get("body") or ""),
                    commit_id=review["commit_id"], in_reply_to_id=None)
        return 200, _public(review)
    if (listed := re.fullmatch(r"/pulls/(\d+)/reviews/(\d+)/comments", rest)) and method == "GET":
        return 200, _page([_public(row) for row in mine("review_comments")
                           if (row["pull"], row["review"]) == (int(listed[1]), int(listed[2]))], query)
    if rest == "/pulls/comments" and method == "GET":
        web = store.base_url.removesuffix("/api/v3")
        api = f"{store.base_url}/repos/{owner}/{repo}"
        return 200, _page([{**_public(row), "pull_request_url": f"{api}/pulls/{row['pull']}",
                            "html_url": f"{web}/{owner}/{repo}/pull/{row['pull']}#discussion_r{row['id']}"}
                           for row in _since(mine("review_comments"), query)], query)
    if (reply := re.fullmatch(r"/pulls/(\d+)/comments/(\d+)/replies", rest)) and method == "POST":
        parent = next((row for row in mine("review_comments") if row["id"] == int(reply[2])), None)
        if parent is None:
            return 404, {"message": "Not Found"}
        return 201, _public(_record(store, "review_comments", owner, repo, pull=int(reply[1]),
                                    review=parent["review"], path=parent["path"], line=parent["line"],
                                    body=str(body.get("body") or ""), commit_id=parent["commit_id"],
                                    in_reply_to_id=parent["id"]))
    if (status := re.fullmatch(r"/statuses/([0-9a-f]{7,40})", rest)) and method == "POST":
        return 201, _public(_record(store, "statuses", owner, repo, sha=status[1],
                                    **{key: str(body.get(key) or "") for key in ("state", "context", "description",
                                                                                  "target_url")}))
    if (commit := re.fullmatch(r"/commits/([^/]+)/(statuses|check-runs)", rest)) and method == "GET":
        if commit[2] == "check-runs":
            return 200, {"total_count": 0, "check_runs": []}
        sha = store.sha(owner, repo, unquote(commit[1])) or unquote(commit[1])
        return 200, _page([_public(row) for row in reversed(mine("statuses")) if row["sha"] == sha], query)
    if re.fullmatch(r"/collaborators/[^/]+/permission", rest) and method == "GET":
        return 200, {"permission": "admin", "user": BOT}
    return None


def handle_pulls(store: Store, method: str, owner: str, repo: str, rest: str, query: dict[str, list[str]],
                 body: Any) -> tuple[int, Any]:
    pulls = [pull for pull in store.state["pulls"] if pull["owner"] == owner and pull["repo"] == repo]
    if rest == "/pulls" and method == "GET":
        state = (query.get("state") or ["open"])[0]
        head = (query.get("head") or [""])[0].split(":")[-1]
        return 200, _page([store.pull_json(pull) for pull in pulls
                           if (state == "all" or pull["state"] == state) and (not head or pull["head"] == head)], query)
    if rest == "/pulls" and method == "POST":
        head, base = str(body.get("head") or "").split(":")[-1], str(body.get("base") or "")
        if not store.sha(owner, repo, head):
            return 422, {"message": "Validation Failed", "errors": [{"field": "head", "code": "invalid"}]}
        if any(pull["head"] == head and pull["state"] == "open" for pull in pulls):
            return 422, {"message": "Validation Failed",
                         "errors": [{"message": f"A pull request already exists for {owner}:{head}."}]}
        pull = {"owner": owner, "repo": repo, "number": len(store.state["pulls"]) + 1, "state": "open",
                "title": str(body.get("title") or ""), "body": str(body.get("body") or ""), "head": head,
                "base": base or store.default_branch(owner, repo), "reviewers": [], "created_at": now(),
                "updated_at": now()}
        store.state["pulls"].append(pull)
        store.save()
        return 201, store.pull_json(pull)
    match = re.fullmatch(r"/pulls/(\d+)(/requested_reviewers)?", rest)
    pull = next((item for item in pulls if match and item["number"] == int(match[1])), None)
    if pull is None:
        return 404, {"message": "Not Found"}
    if match[2] and method == "POST":
        pull["reviewers"] = sorted({*pull["reviewers"], *[str(name) for name in body.get("reviewers") or []]})
    elif method == "PATCH":
        for key in ("title", "body", "base", "state"):
            if key in (body or {}):
                pull[key] = str(body[key])
    pull["updated_at"] = now()
    store.save()
    return (201 if match[2] else 200), store.pull_json(pull)


def git_http_backend(store: Store, handler: BaseHTTPRequestHandler, path: str, query: str, body: bytes) -> None:
    """``git http-backend`` as CGI: clone, fetch and push over ``/<owner>/<repo>.git/...``."""
    env = {**os.environ, "GIT_PROJECT_ROOT": str(store.root), "GIT_HTTP_EXPORT_ALL": "1", "PATH_INFO": path,
           "REQUEST_METHOD": handler.command, "QUERY_STRING": query, "REMOTE_USER": "demo", "REMOTE_ADDR": "127.0.0.1",
           "CONTENT_TYPE": handler.headers.get("Content-Type", ""), "CONTENT_LENGTH": str(len(body))}
    if handler.headers.get("Content-Encoding"):
        env["HTTP_CONTENT_ENCODING"] = handler.headers["Content-Encoding"]
    if handler.headers.get("Git-Protocol"):
        env["GIT_PROTOCOL"] = handler.headers["Git-Protocol"]
    done = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True, check=False)
    head, _, payload = done.stdout.partition(b"\r\n\r\n")
    if not _:
        head, _, payload = done.stdout.partition(b"\n\n")
    status, headers = 200, []
    for line in head.decode("latin-1").splitlines():
        name, _, value = line.partition(":")
        if name.lower() == "status":
            status = int(value.strip().split()[0])
        elif name:
            headers.append((name.strip(), value.strip()))
    handler.send_response(status)
    for name, value in headers:
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


# Read-only pull request pages support the demo's "Open the pull request" links.

_PULL_PAGE = re.compile(r"/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)")
_DIFF_LIMIT = 200_000
_PAGE_STYLE = """
:root { color-scheme: light dark; --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --line: #d1d9e0; --box: #f6f8fa;
  --add: #1a7f37; --del: #cf222e; --accent: #0969da; }
@media (prefers-color-scheme: dark) { :root { --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --line: #3d444d;
  --box: #151b23; --add: #3fb950; --del: #f85149; --accent: #4493f8; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.5 system-ui, -apple-system, "Segoe UI",
  sans-serif; }
main { max-width: 1012px; margin: 0 auto; padding: 24px 16px 48px; }
header p, .muted { color: var(--muted); }
h1 { font-size: 26px; font-weight: 400; margin: 0 0 8px; } h1 span { color: var(--muted); }
h2 { font-size: 16px; margin: 28px 0 8px; }
.state { display: inline-block; padding: 2px 10px; border-radius: 999px; background: var(--add); color: #fff;
  font-weight: 600; margin-right: 6px; }
.box { border: 1px solid var(--line); border-radius: 6px; margin: 12px 0; overflow: hidden; }
.box > .head { background: var(--box); border-bottom: 1px solid var(--line); padding: 8px 12px; color: var(--muted); }
.box > .text { padding: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.inline { border-top: 1px solid var(--line); padding: 8px 12px 8px 24px; }
.inline code, code { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
pre { margin: 0; padding: 12px; overflow-x: auto; font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }
.add { color: var(--add); } .del { color: var(--del); }
details > summary { cursor: pointer; padding: 8px 12px; background: var(--box); }
ul.statuses { list-style: none; padding: 0; margin: 0; } ul.statuses li { padding: 8px 12px; }
ul.statuses li + li { border-top: 1px solid var(--line); }
.ok { color: var(--add); font-weight: 600; } .bad { color: var(--del); font-weight: 600; }
"""


def _text(value: Any) -> str:
    return html.escape(str(value or ""))


def _diff_lines(diff: str) -> str:
    lines = []
    for line in diff.splitlines():
        kind = "add" if line.startswith("+") and not line.startswith("+++") else (
            "del" if line.startswith("-") and not line.startswith("---") else "")
        lines.append(f'<span class="{kind}">{_text(line)}</span>' if kind else _text(line))
    return "\n".join(lines)


def pull_page(store: Store, owner: str, repo: str, number: int) -> str | None:
    """One pull request as GitHub would show its conversation, built only from this fake's own records."""
    pull = next((item for item in store.state.get("pulls", [])
                 if (item["owner"], item["repo"], item["number"]) == (owner, repo, number)), None)
    if pull is None:
        return None
    activity = store.activity(pull)
    base, head = pull["base"], pull["head"]
    stat = store.git(owner, repo, "diff", "--stat", f"refs/heads/{base}...refs/heads/{head}", check=False)
    diff = store.git(owner, repo, "diff", f"refs/heads/{base}...refs/heads/{head}", check=False)
    cut = len(diff) > _DIFF_LIMIT
    reviewers = ", ".join(str(name) for name in pull.get("reviewers") or []) or "none"
    parts = [f"<header><h1>{_text(pull['title'])} <span>#{number}</span></h1>",
             f'<p><span class="state">{_text(pull["state"]).capitalize()}</span>{_text(BOT["login"])} wants to merge '
             f"<code>{_text(head)}</code> into <code>{_text(base)}</code> in {_text(owner)}/{_text(repo)} · "
             f"reviewers: {_text(reviewers)}</p></header>",
             f'<div class="box"><div class="head">Description</div><div class="text">{_text(pull["body"])}</div></div>',
             "<h2>Files changed</h2>",
             f'<div class="box"><pre>{_text(stat) or "No change."}</pre>',
             f"<details><summary>Show the diff{' (cut at 200 KB)' if cut else ''}</summary>"
             f"<pre>{_diff_lines(diff[:_DIFF_LIMIT])}</pre></details></div>",
             "<h2>Conversation</h2>"]
    for row in activity["comments"]:
        parts.append(f'<div class="box" id="issuecomment-{row["id"]}"><div class="head">{_text(row["user"]["login"])} '
                     f'commented · {_text(row["created_at"])}</div><div class="text">{_text(row["body"])}</div></div>')
    for review in activity["reviews"]:
        inline = [row for row in activity["review_comments"] if row.get("review") == review["id"]]
        notes = "".join(f'<div class="inline" id="discussion_r{row["id"]}"><code>{_text(row["path"])}'
                        f'{":" + _text(row["line"]) if row.get("line") else ""}</code>'
                        f'<div class="text">{_text(row["body"])}</div></div>' for row in inline)
        parts.append(f'<div class="box"><div class="head">{_text(review["user"]["login"])} reviewed '
                     f'{_text(str(review.get("commit_id") or "")[:7])} · {_text(review["created_at"])}</div>'
                     + (f'<div class="text">{_text(review["body"])}</div>' if review.get("body") else "")
                     + f"{notes}</div>")
    if not activity["comments"] and not activity["reviews"]:
        parts.append('<p class="muted">No comments or reviews yet.</p>')
    latest = {row.get("context"): row for row in activity["statuses"]}  # GitHub shows a context's last status only
    statuses = "".join(f'<li><span class="{"ok" if row.get("state") == "success" else "bad"}">'
                       f'{_text(row.get("state"))}</span> <code>{_text(row.get("context"))}</code> '
                       f'{_text(row.get("description"))}</li>' for row in latest.values())
    parts.append(f'<h2>Checks</h2><div class="box"><ul class="statuses">{statuses or "<li>No status yet.</li>"}'
                 "</ul></div>")
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{_text(pull['title'])} · #{number}</title><style>{_PAGE_STYLE}</style></head>"
            f"<body><main>{''.join(parts)}</main></body></html>")


def read_body(handler: BaseHTTPRequestHandler) -> bytes:
    if handler.headers.get("Transfer-Encoding", "").lower() == "chunked":
        chunks = []
        while True:
            size = int(handler.rfile.readline().split(b";")[0].strip() or b"0", 16)
            if size == 0:
                handler.rfile.readline()
                return b"".join(chunks)
            chunks.append(handler.rfile.read(size))
            handler.rfile.readline()
    length = int(handler.headers.get("Content-Length") or 0)
    return handler.rfile.read(length) if length else b""


def make_handler(store: Store) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "fake-github/1"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write(f"fake-github {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")

        def dispatch(self) -> None:
            parts = urlsplit(self.path)
            raw = read_body(self)
            if ".git/" in parts.path or parts.path.endswith(".git"):
                with LOCK:
                    git_http_backend(store, self, parts.path, parts.query, raw)
                return
            page = _PULL_PAGE.fullmatch(parts.path.rstrip("/")) if self.command == "GET" else None
            if page is not None:
                with LOCK:
                    text = pull_page(store, page["owner"], page["repo"], int(page["number"]))
                data = (text or "<!doctype html><title>Not Found</title><p>No such pull request.").encode()
                self.send_response(200 if text else 404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                body = {}
            try:
                with LOCK:
                    status, payload = handle_api(store, self.command, parts.path.rstrip("/") or "/",
                                                 parse_qs(parts.query), body)
            except Exception as exc:  # noqa: BLE001 - a fake answers 500 with the reason, never dies
                status, payload = 500, {"message": f"fake error: {type(exc).__name__}: {exc}"}
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = dispatch

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8434)
    parser.add_argument("--root", default="remotes")
    parser.add_argument("--public-url", default="", help="the base URL in links (default http://<host>:<port>)")
    args = parser.parse_args()
    public = (args.public_url or f"http://{args.host}:{args.port}").rstrip("/")
    store = Store(Path(args.root), f"{public}/api/v3")
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    sys.stderr.write(f"fake-github on http://{args.host}:{args.port} as {public} (repos under {args.root})\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
