"""The closed table of Git hosts, and the identity of one repository."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from ...ledger.errors import InvalidEvidenceRequestError

SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_REPOSITORY_URL_CHARS = 300
MAX_PATH_SEGMENTS = 5
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{1,100}$")
_HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class GitHost:
    name: str
    web_base: str
    api_base: str
    archive_base: str
    owner: re.Pattern = _OWNER
    # The connector whose connection reads this host ("" : public, no credential), and the JSON key of the commit
    # answer ("": the plain sha GitHub answers for ``application/vnd.github.sha``).
    credential_connector: str = ""
    commit_json_key: str = ""

    def commit_url(self, path: str, ref: str) -> str:
        return f"{self.api_base}/repos/{path}/commits/{quote(ref, safe='')}"

    def archive_url(self, path: str, sha: str) -> str:
        return f"{self.archive_base}/{path}/tar.gz/{sha}"

    def api_archive_url(self, path: str, sha: str) -> str:
        return f"{self.api_base}/repos/{path}/tarball/{sha}"

    def tree_url(self, path: str, sha: str) -> str:
        return f"{self.api_base}/repos/{path}/git/trees/{sha}"

    def blob_url(self, path: str, sha: str, file_path: str) -> str:
        return f"{self.web_base}/{path}/blob/{sha}/{quote(file_path, safe='/')}"


GITHUB = GitHost(
    name="github.com",
    web_base="https://github.com",
    api_base="https://api.github.com",
    archive_base="https://codeload.github.com",
)


@dataclass(frozen=True, slots=True)
class BitbucketCloudHost(GitHost):
    def commit_url(self, path: str, ref: str) -> str:
        return f"{self.api_base}/repositories/{path}/commit/{quote(ref, safe='')}"

    def archive_url(self, path: str, sha: str) -> str:
        return f"{self.archive_base}/{path}/get/{sha}.tar.gz"

    def blob_url(self, path: str, sha: str, file_path: str) -> str:
        return f"{self.web_base}/{path}/src/{sha}/{quote(file_path, safe='/')}"


BITBUCKET_CLOUD = BitbucketCloudHost(
    name="bitbucket.org",
    web_base="https://bitbucket.org",
    api_base="https://api.bitbucket.org/2.0",
    archive_base="https://bitbucket.org",
    owner=re.compile(r"^[a-z0-9][a-z0-9_-]{0,61}$"),
    credential_connector="bitbucket",
    commit_json_key="hash",
)
GIT_HOSTS: dict[str, GitHost] = {GITHUB.name: GITHUB, BITBUCKET_CLOUD.name: BITBUCKET_CLOUD}

HOST_BITBUCKET_DATACENTER = "bitbucket_datacenter"
_DC_PROJECT = re.compile(r"^~?[A-Za-z0-9_]{1,128}$")
_DC_SLUG = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_DC_BASE_PATH = re.compile(r"^(?:/[A-Za-z0-9._~-]{1,64}){0,3}$")


@dataclass(frozen=True, slots=True)
class BitbucketDataCenterHost(GitHost):
    def repository_url(self, path: str) -> str:
        project, slug = path.split("/", 1)
        return f"{self.web_base}/projects/{project}/repos/{slug}"

    def clone_url(self, path: str) -> str:
        project, slug = path.split("/", 1)
        return f"{self.web_base}/scm/{project.lower()}/{slug}.git"

    def blob_url(self, path: str, sha: str, file_path: str) -> str:
        return f"{self.repository_url(path)}/browse/{quote(file_path, safe='/')}?at={sha}"


def datacenter_base(raw: object) -> str | None:
    if type(raw) is not str or len(raw) > MAX_REPOSITORY_URL_CHARS:
        return None
    parts = urlsplit(raw.strip())
    try:
        port = parts.port
    except ValueError:
        return None
    hostname = (parts.hostname or "").lower()
    path = parts.path.rstrip("/")
    if parts.scheme != "https" or parts.username or parts.password or parts.query or parts.fragment:
        return None
    if not _HOSTNAME.fullmatch(hostname) or "." not in hostname or not _DC_BASE_PATH.fullmatch(path):
        return None
    return f"https://{hostname}{f':{port}' if port else ''}{path}"


def datacenter_host(base: str) -> BitbucketDataCenterHost:
    hostname = urlsplit(base).hostname or ""
    return BitbucketDataCenterHost(
        name=hostname, web_base=base, api_base=f"{base}/rest/api/1.0", archive_base=base,
        credential_connector="bitbucket",
    )


def parse_datacenter_repository(raw: object, base: str) -> RepositoryLocation:
    canonical = datacenter_base(base)
    if canonical is None or type(raw) is not str or len(raw) > MAX_REPOSITORY_URL_CHARS:
        raise InvalidEvidenceRequestError()
    parts = urlsplit(raw.strip())
    try:
        port = parts.port
    except ValueError:
        raise InvalidEvidenceRequestError() from None
    if parts.username or parts.password or parts.query or parts.fragment:
        raise InvalidEvidenceRequestError()
    origin = f"{parts.scheme}://{(parts.hostname or '').lower()}{f':{port}' if port else ''}"
    path = parts.path.rstrip("/")
    prefix = canonical[len(origin):] if canonical.startswith(origin + "/") or canonical == origin else None
    if prefix is None or not (path == prefix or path.startswith(prefix + "/")):
        raise InvalidEvidenceRequestError()
    segments = path[len(prefix):].strip("/").split("/")
    if len(segments) == 4 and segments[0] == "projects" and segments[2] == "repos":
        project, slug = segments[1], segments[3]
    elif len(segments) == 5 and segments[0] == "projects" and segments[2] == "repos" and segments[4] == "browse":
        project, slug = segments[1], segments[3]
    elif len(segments) == 3 and segments[0] == "scm":
        project, slug = segments[1], segments[2].removesuffix(".git")
    else:
        raise InvalidEvidenceRequestError()
    if not _DC_PROJECT.fullmatch(project) or not _DC_SLUG.fullmatch(slug) or slug in (".", ".."):
        raise InvalidEvidenceRequestError()
    project = project if project.startswith("~") else project.upper()
    host = datacenter_host(canonical)
    return RepositoryLocation(hostname=host.name, path=f"{project}/{slug.lower()}", host=host)


@dataclass(frozen=True, slots=True)
class RepositoryLocation:
    hostname: str
    path: str
    host: GitHost | None

    @property
    def url(self) -> str:
        if isinstance(self.host, BitbucketDataCenterHost):
            return self.host.repository_url(self.path)
        return f"https://{self.hostname}/{self.path}"

    @property
    def slug(self) -> str:
        return f"{self.hostname}/{self.path}"

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    def blob_url(self, sha: str, file_path: str) -> str | None:
        return self.host.blob_url(self.path, sha, file_path) if self.host is not None else None


def parse_repository_url(raw: object, *, known_host_only: bool) -> RepositoryLocation:
    if type(raw) is not str or len(raw) > MAX_REPOSITORY_URL_CHARS:
        raise InvalidEvidenceRequestError()
    parts = urlsplit(raw.strip())
    if parts.scheme != "https" or parts.query or parts.fragment or parts.username or parts.password:
        raise InvalidEvidenceRequestError()
    try:
        port = parts.port
    except ValueError:
        raise InvalidEvidenceRequestError() from None
    hostname = (parts.hostname or "").lower()
    if port is not None or not _HOSTNAME.fullmatch(hostname) or "." not in hostname:
        raise InvalidEvidenceRequestError()
    host = GIT_HOSTS.get(hostname)
    if host is None and known_host_only:
        raise InvalidEvidenceRequestError()
    segments = parts.path.strip("/").split("/")
    if host is not None and (len(segments) != 2 or not host.owner.fullmatch(segments[0])):
        raise InvalidEvidenceRequestError()
    if not 1 <= len(segments) <= MAX_PATH_SEGMENTS or not all(_SEGMENT.fullmatch(part) for part in segments):
        raise InvalidEvidenceRequestError()
    if any(part in (".", "..") for part in segments) or segments[-1].endswith(".git"):
        raise InvalidEvidenceRequestError()
    return RepositoryLocation(hostname=hostname, path="/".join(segments), host=host)


__all__ = [
    "BITBUCKET_CLOUD",
    "GITHUB",
    "GIT_HOSTS",
    "HOST_BITBUCKET_DATACENTER",
    "SHA",
    "BitbucketDataCenterHost",
    "GitHost",
    "RepositoryLocation",
    "datacenter_base",
    "datacenter_host",
    "parse_datacenter_repository",
    "parse_repository_url",
]
