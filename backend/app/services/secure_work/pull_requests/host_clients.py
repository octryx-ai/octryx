"""Read a pull request from its host on the target's resolved connection (read only).

One client per deployment: ``read`` → ``HostRead`` (the mapped pull request and its head commit's build status; a
failed build read is reported in ``build_error`` and never fails the pull request read).

Bitbucket Server/Data Center: REST 1.0 (``pull-requests/{id}``, build status ``/rest/build-status/1.0/commits/{sha}``).
Bitbucket Cloud: REST 2.0 (``pullrequests/{id}``, ``commit/{sha}/statuses``). GitHub: ``pulls/{n}`` and its
reviews, the combined ``commits/{sha}/status``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from app.tools.bitbucket_impl import _bitbucket_internal_network

from ....tools.bitbucket_impl import _bitbucket_cloud_ops as cloud_ops
from ....tools.bitbucket_impl._bitbucket_cloud import cloud_request, repo_path
from ....tools.connectors.github import _github_base_url, _github_headers, _http_json
from .host_state import (
    HostPullRequest,
    HostStateError,
    aggregate_build_status,
    bitbucket_cloud_state,
    bitbucket_server_state,
    github_state,
)
from .host_target import (
    DEPLOYMENT_CLOUD,
    DEPLOYMENT_GITHUB,
    DEPLOYMENT_SERVER,
    HostTarget,
    PullRequestHostError,
    host_error,
)

_HOSTS = {DEPLOYMENT_SERVER: "Bitbucket", DEPLOYMENT_CLOUD: "Bitbucket Cloud", DEPLOYMENT_GITHUB: "GitHub"}


@dataclass(slots=True)
class HostRead:
    pull_request: HostPullRequest
    build_status: str | None = None
    build_error: PullRequestHostError | None = None


class PullRequestHost(Protocol):
    async def read(self, target: HostTarget) -> HostRead: ...


async def _build(target: HostTarget, read_states) -> tuple[str | None, PullRequestHostError | None]:
    try:
        return aggregate_build_status(await read_states()), None
    except HostStateError as error:
        return None, PullRequestHostError(error.code, error.message)
    except Exception as error:  # the build read is optional: its failure is reported, the PR read stands
        return None, host_error(error, _HOSTS[target.deployment])


class BitbucketServerHost:
    def _base(self, target: HostTarget) -> str:
        return (f"/rest/api/1.0/projects/{quote(target.owner, safe='')}/repos/{quote(target.repo, safe='')}"
                f"/pull-requests/{target.number}")

    async def read(self, target: HostTarget) -> HostRead:
        payload = await _bitbucket_internal_network._bitbucket_json_get(target.context, self._base(target))
        mapped = bitbucket_server_state(payload)
        if not mapped.head_commit:
            return HostRead(mapped)

        async def states() -> list[Any]:
            page = await _bitbucket_internal_network._bitbucket_json_get(
                target.context, f"/rest/build-status/1.0/commits/{quote(mapped.head_commit, safe='')}")
            return [item.get("state") for item in (page or {}).get("values") or []]

        build, error = await _build(target, states)
        return HostRead(mapped, build, error)


class BitbucketCloudHost:
    def _path(self, target: HostTarget) -> str:
        return f"{repo_path(target.owner, target.repo)}/pullrequests/{target.number}"

    async def read(self, target: HostTarget) -> HostRead:
        mapped = bitbucket_cloud_state(await cloud_request(target.context, "GET", self._path(target)) or {})
        if not mapped.head_commit:
            return HostRead(mapped)

        async def states() -> list[Any]:
            statuses = await cloud_ops.build_statuses(target.context, target.owner, target.repo, mapped.head_commit)
            return [item.get("state") for item in statuses]

        build, error = await _build(target, states)
        return HostRead(mapped, build, error)


class GitHubHost:
    async def _get(self, target: HostTarget, path: str, **params: Any) -> Any:
        return await _http_json("GET", f"{_github_base_url(target.context)}{path}",
                                headers=await _github_headers(target.context), params=params or None)

    def _pull(self, target: HostTarget) -> str:
        return f"/repos/{quote(target.owner, safe='')}/{quote(target.repo, safe='')}/pulls/{target.number}"

    async def read(self, target: HostTarget) -> HostRead:
        pull = await self._get(target, self._pull(target))
        reviews = await self._get(target, f"{self._pull(target)}/reviews", per_page=100)
        mapped = github_state(pull or {}, list(reviews or []))
        if not mapped.head_commit:
            return HostRead(mapped)

        async def states() -> list[Any]:
            combined = await self._get(target, f"/repos/{quote(target.owner, safe='')}/"
                                               f"{quote(target.repo, safe='')}/commits/{mapped.head_commit}/status")
            if not int((combined or {}).get("total_count") or 0):
                return []
            return [(combined or {}).get("state")]

        build, error = await _build(target, states)
        return HostRead(mapped, build, error)


_CLIENTS: dict[str, PullRequestHost] = {DEPLOYMENT_SERVER: BitbucketServerHost(),
                                        DEPLOYMENT_CLOUD: BitbucketCloudHost(), DEPLOYMENT_GITHUB: GitHubHost()}


def client_for(target: HostTarget) -> PullRequestHost:
    return _CLIENTS[target.deployment]


def host_name(target: HostTarget) -> str:
    return _HOSTS[target.deployment]


__all__ = ["BitbucketCloudHost", "BitbucketServerHost", "GitHubHost", "HostRead", "PullRequestHost",
           "client_for", "host_name"]
