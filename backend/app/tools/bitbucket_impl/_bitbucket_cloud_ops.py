"""Bitbucket Cloud operations of the Bitbucket tools, in the shapes the Server/Data Center tools return.

- **repository**: the default branch is the repository's ``mainbranch``; a branch head is ``refs/branches/<name>``;
- **branch**: ``POST refs/branches`` from the start point's commit;
- **pull request**: created with ``source``/``destination`` branches and reviewers by Atlassian account id. Every
  reviewer is checked first (``GET /users/<account id>``): an unknown one is listed in ``reviewers_unresolved``
  and not sent. Bitbucket never lets the pull request's author review it: a requester who is the connection's own
  account is mentioned in the description instead (``scm_requester_rule``, ``reviewer_skipped``; the account lookup is
  best-effort, a refused requester-reviewer with an unknown author opens the PR without them: ``reviewer_refused``);
- **pull request state**: ``OPEN`` / ``MERGED`` / ``DECLINED`` / ``SUPERSEDED``, with each reviewer's approval from
  the participants;
- **comment**: ``POST pullrequests/<id>/comments`` (markdown ``raw``);
- **build statuses**: ``commit/<sha>/statuses`` (Bitbucket Pipelines and any other reporter), each with its state
  ``SUCCESSFUL`` / ``FAILED`` / ``INPROGRESS`` / ``STOPPED``; a Pipelines build's per-step test reports
  (``pipelines/<n>/steps/<uuid>/test_reports/test_cases``) on request; a step without a report has none.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from app.tools.context import ToolContext

from ...services.ai_marking import MarkingFacts, with_marker
from ..scm_requester_rule import REVIEWER_REFUSED, apply_requester_rule, connection_author, refused_note
from ._bitbucket_cloud import CloudApiError, cloud_request, repo_path, web_url

SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_STATUSES = 100


def _ref(name: str) -> str:
    return quote(name, safe="")


async def default_branch(context: ToolContext, workspace: str, slug: str) -> str:
    repository = await cloud_request(context, "GET", repo_path(workspace, slug))
    name = str(((repository or {}).get("mainbranch") or {}).get("name") or "").strip()
    if not name:
        raise CloudApiError(0, f"Repository {workspace}/{slug} has no main branch yet (an empty repository).")
    return name


async def branch_head(context: ToolContext, workspace: str, slug: str, branch: str) -> str:
    ref = await cloud_request(context, "GET", f"{repo_path(workspace, slug)}/refs/branches/{_ref(branch)}")
    return str(((ref or {}).get("target") or {}).get("hash") or "")


async def create_branch(context: ToolContext, workspace: str, slug: str, name: str, start_point: str) -> dict[str, Any]:
    start = start_point or await default_branch(context, workspace, slug)
    commit = start if SHA.fullmatch(start) else await branch_head(context, workspace, slug, start)
    created = await cloud_request(context, "POST", f"{repo_path(workspace, slug)}/refs/branches",
                                  payload={"name": name, "target": {"hash": commit}})
    return {"branch_name": str((created or {}).get("name") or name), "start_point": start,
            "latest_commit": str(((created or {}).get("target") or {}).get("hash") or commit)}


def pr_summary(pr: dict[str, Any]) -> dict[str, Any]:
    """A Cloud pull request in the Server tool's summary shape, plus ``url`` and reviewers' account ids."""
    reviewers = [
        {"name": (item.get("user") or {}).get("display_name"), "account_id": (item.get("user") or {}).get("account_id"),
         "approved": bool(item.get("approved"))}
        for item in pr.get("participants") or [] if item.get("role") == "REVIEWER"
    ]
    url = str(((pr.get("links") or {}).get("html") or {}).get("href") or "")
    return {
        "id": pr.get("id"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "description": (pr.get("description") or "")[:500],
        "author": (pr.get("author") or {}).get("display_name"),
        "from_branch": ((pr.get("source") or {}).get("branch") or {}).get("name"),
        "to_branch": ((pr.get("destination") or {}).get("branch") or {}).get("name"),
        "created_date": pr.get("created_on"),
        "updated_date": pr.get("updated_on"),
        "reviewers": reviewers,
        "links": url,
        "url": url,
        "source_commit": ((pr.get("source") or {}).get("commit") or {}).get("hash"),
    }


async def find_open_pr(context: ToolContext, workspace: str, slug: str, from_branch: str) -> dict[str, Any] | None:
    query = f'state="OPEN" AND source.branch.name="{from_branch.replace(chr(34), "")}"'
    page = await cloud_request(context, "GET", f"{repo_path(workspace, slug)}/pullrequests",
                               params={"q": query, "pagelen": 10})
    return next((pr for pr in (page or {}).get("values") or []
                 if ((pr.get("source") or {}).get("branch") or {}).get("name") == from_branch), None)


async def get_pr(context: ToolContext, workspace: str, slug: str, pr_id: str) -> dict[str, Any]:
    return pr_summary(await cloud_request(context, "GET", f"{repo_path(workspace, slug)}/pullrequests/{_ref(pr_id)}"))


async def _checked_reviewers(context: ToolContext, reviewers: list[str]) -> tuple[list[str], list[str]]:
    """``(known account ids, unresolved)``: an id Bitbucket does not know is reported and not sent."""
    known: list[str] = []
    unresolved: list[str] = []
    for account_id in dict.fromkeys(item.strip() for item in reviewers if item and item.strip()):
        try:
            user = await cloud_request(context, "GET", f"/users/{_ref(account_id)}")
        except CloudApiError as error:
            if error.status != 404:
                raise
            user = None
        (known if user else unresolved).append(account_id)
    return known, unresolved


async def create_pr(
    context: ToolContext, workspace: str, slug: str, *, title: str, description: str, from_branch: str,
    to_branch: str, reviewers: list[str], requester: str = "", marking: MarkingFacts | None = None,
) -> dict[str, Any]:
    existing = await find_open_pr(context, workspace, slug, from_branch)
    if existing is not None:
        return {**pr_summary(existing), "status": "existing", "reviewers_unresolved": []}
    skipped, author = "", ""
    if reviewers:
        async def account_id() -> str:
            return str((await cloud_request(context, "GET", "/user") or {}).get("account_id") or "")

        author = await connection_author("bitbucket_cloud", account_id)
        reviewers, description, skipped = apply_requester_rule(
            reviewers, requester=requester, author=author, description=description, mention=f"@{{{requester}}}",
            exact=True)
    known, unresolved = await _checked_reviewers(context, reviewers)
    target = to_branch or await default_branch(context, workspace, slug)

    async def create(with_reviewers: list[str], text: str) -> Any:
        return await cloud_request(context, "POST", f"{repo_path(workspace, slug)}/pullrequests", payload={
            "title": title, "description": with_marker(text, marking), "close_source_branch": False,
            "source": {"branch": {"name": from_branch}}, "destination": {"branch": {"name": target}},
            "reviewers": [{"account_id": item} for item in with_reviewers],
        })

    try:
        created = await create(known, description)
    except CloudApiError as error:
        # The author unknown, Bitbucket refuses the whole pull request when a reviewer is its author: open it once
        # more without the requester as reviewer and mention them; any other refusal still fails the step.
        if error.status != 400 or author or requester not in known:
            raise
        known = [item for item in known if item != requester]
        created = await create(known, refused_note(description, f"@{{{requester}}}"))
        skipped = REVIEWER_REFUSED
    return {**pr_summary(created or {}), "status": "created", "reviewers_unresolved": unresolved,
            "to_branch": target, **({"reviewer_skipped": skipped} if skipped else {})}


async def comment_pr(context: ToolContext, workspace: str, slug: str, pr_id: str, text: str) -> dict[str, Any]:
    comment = await cloud_request(context, "POST", f"{repo_path(workspace, slug)}/pullrequests/{_ref(pr_id)}/comments",
                                  payload={"content": {"raw": text}})
    url = str((((comment or {}).get("links") or {}).get("html") or {}).get("href") or "")
    return {"comment_id": (comment or {}).get("id"), "url": url}


async def build_statuses(context: ToolContext, workspace: str, slug: str, commit: str) -> list[dict[str, Any]]:
    page = await cloud_request(context, "GET", f"{repo_path(workspace, slug)}/commit/{_ref(commit)}/statuses",
                               params={"pagelen": MAX_STATUSES})
    return [{"state": str(item.get("state") or ""), "key": item.get("key"), "name": item.get("name"),
             "url": item.get("url"), "commit": commit} for item in (page or {}).get("values") or []]


_PIPELINE_RESULT = re.compile(r"/pipelines/results/(?P<number>\d{1,10})(?:[/?#]|$)")
MAX_TEST_CASES = 2000


def pipeline_number(url: str) -> str:
    """The Pipelines build number a build status links to (``…/pipelines/results/<n>``), else ``''``."""
    match = _PIPELINE_RESULT.search(str(url or ""))
    return match["number"] if match else ""


async def pipeline_test_cases(context: ToolContext, workspace: str, slug: str, number: str) -> list[dict[str, Any]]:
    """Every test case the build's steps reported (``{"classname", "name", "file", "status", "message"}``).

    A step without a test report (Bitbucket's 404 on its ``test_cases``) contributes none; any other refusal raises."""
    pipeline = f"{repo_path(workspace, slug)}/pipelines/{quote(number, safe='')}"
    steps = await cloud_request(context, "GET", f"{pipeline}/steps/", params={"pagelen": 100})
    cases: list[dict[str, Any]] = []
    for step in (steps or {}).get("values") or []:
        uuid = str(step.get("uuid") or "")
        if not uuid:
            continue
        try:
            page = await cloud_request(context, "GET",
                                       f"{pipeline}/steps/{quote(uuid, safe='')}/test_reports/test_cases",
                                       params={"pagelen": 100})
        except CloudApiError as error:
            if error.status != 404:
                raise
            continue  # Bitbucket answers 404 for a step that reported no tests (a lint or deploy step)
        for case in (page or {}).get("values") or []:
            name = str(case.get("name") or "")
            qualified = str(case.get("fully_qualified_name") or "")
            classname = qualified[: -len(name) - 1] if name and qualified.endswith("." + name) else (
                qualified.rsplit(".", 1)[0] if "." in qualified else "")
            cases.append({"classname": classname, "name": name or qualified.rsplit(".", 1)[-1], "file": "",
                          "status": str(case.get("status") or ""), "message": ""})
            if len(cases) >= MAX_TEST_CASES:
                return cases
    return cases


def repository_web_url(workspace: str, slug: str) -> str:
    return web_url(workspace, slug)


__all__ = ["branch_head", "build_statuses", "comment_pr", "create_branch", "create_pr",
           "default_branch", "find_open_pr", "get_pr", "pipeline_number", "pipeline_test_cases", "pr_summary",
           "repository_web_url"]
