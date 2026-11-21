"""The pinned public repositories of the code-question eval, their ground truth, and the citation rule.

- ``PinnedRepo``: a GitHub repository at one commit. ``tree()`` lists its files at that commit
  (GitHub trees API) and ``raw(path)`` reads one file at that commit (raw.githubusercontent), so the
  expected answers are verified against the repository itself, never against memory.
- ``classify(url, repo, tree)``: a citation is ``pinned`` only as a GitHub blob URL of this
  repository at the pinned commit naming a file that exists there (``#L12`` or ``#L12-L20`` line
  anchors are recorded); any other link into the repository is ``unpinned``, a blob path that does
  not exist is ``missing_path``, everything else is ``outside``.

Nothing here prints file content.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

_TIMEOUT_SECONDS = 30
_LINK = re.compile(r"https?://[^\s)\]>\"'<`|]+")


@dataclass(frozen=True, slots=True)
class PinnedRepo:
    owner: str
    name: str
    sha: str
    label: str

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    def blob_url(self, path: str) -> str:
        return f"{self.url}/blob/{self.sha}/{path}"

    def tree(self) -> frozenset[str]:
        """Every file path at the pinned commit; refuses a truncated listing."""
        api = f"https://api.github.com/repos/{self.slug}/git/trees/{self.sha}?recursive=1"
        request = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            listing = json.loads(response.read())
        if listing.get("truncated"):
            raise RuntimeError(f"tree of {self.slug}@{self.sha[:8]} is truncated")
        return frozenset(item["path"] for item in listing.get("tree") or [] if item.get("type") == "blob")

    def raw(self, path: str) -> str:
        url = f"https://raw.githubusercontent.com/{self.slug}/{self.sha}/{path}"
        with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="replace")


PETCLINIC = PinnedRepo(
    "spring-projects", "spring-petclinic", "b26f235250627a235a2974a22f2317dbef27338d", "spring-petclinic 3.5.6"
)
# A larger real Spring codebase (Gradle), last commit on master.
REALWORLD = PinnedRepo(
    "gothinkster",
    "spring-boot-realworld-example-app",
    "ee17e31aafe733d98c4853c8b9a74d7f2f6c924a",
    "spring-boot-realworld-example-app",
)
REPOSITORIES = (PETCLINIC, REALWORLD)

PINNED = "pinned"
UNPINNED = "unpinned"
MISSING_PATH = "missing_path"
OUTSIDE = "outside"


@dataclass(frozen=True, slots=True)
class Citation:
    url: str
    kind: str
    path: str = ""
    anchored: bool = False


def links(text: str) -> list[str]:
    """Every http(s) link in ``text``, in order, without duplicates and trailing punctuation."""
    found = (match.rstrip(".,;:") for match in _LINK.findall(text or ""))
    return list(dict.fromkeys(found))


def classify(url: str, repo: PinnedRepo, tree: frozenset[str]) -> Citation:
    pinned = re.fullmatch(
        rf"https://github\.com/{re.escape(repo.slug)}/blob/{repo.sha}/(?P<path>[^#?]+)(?P<anchor>#L\d+(?:-L\d+)?)?",
        url,
    )
    if pinned is not None:
        path = pinned["path"]
        return Citation(url, PINNED if path in tree else MISSING_PATH, path, bool(pinned["anchor"]))
    into_repo = re.match(rf"https://(?:github\.com|raw\.githubusercontent\.com)/{re.escape(repo.slug)}(?:[/#?]|$)", url)
    return Citation(url, UNPINNED if into_repo else OUTSIDE)


def citation_counts(citations: list[Citation]) -> dict[str, int]:
    counts = {PINNED: 0, UNPINNED: 0, MISSING_PATH: 0, OUTSIDE: 0}
    for citation in citations:
        counts[citation.kind] += 1
    counts["anchored"] = sum(1 for citation in citations if citation.anchored)
    return counts


__all__ = [
    "MISSING_PATH",
    "OUTSIDE",
    "PETCLINIC",
    "PINNED",
    "REALWORLD",
    "REPOSITORIES",
    "UNPINNED",
    "Citation",
    "PinnedRepo",
    "citation_counts",
    "classify",
    "links",
]
