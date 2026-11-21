"""The platforms a user links an account on, and how each one names the account.

- ``atlassian``: an Atlassian Cloud account, named by its **account id** (the same account on Jira Cloud and
  Bitbucket Cloud); verified through a Workspace's Jira Cloud connection, else its Bitbucket Cloud connection;
- ``jira_server`` / ``bitbucket_server``: a Jira or Bitbucket Server/Data Center **username**;
- ``github`` / ``gitlab``: a GitHub login or GitLab username.

A refusal is a :class:`LinkedAccountError` with a fixed ``code``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ATLASSIAN = "atlassian"
JIRA_SERVER = "jira_server"
BITBUCKET_SERVER = "bitbucket_server"
GITHUB = "github"
GITLAB = "gitlab"

ACCOUNT_ID = "account_id"
USERNAME = "username"

# Atlassian account ids: ``<digits>:<uuid>`` or the older 24-hex form; Bitbucket also accepts ``{<uuid>}``.
ATLASSIAN_ACCOUNT_ID = re.compile(r"^(\d+:[0-9a-fA-F-]{36}|[0-9a-f]{24}|\{[0-9a-fA-F-]{36}\})$")
_USERNAME = re.compile(r"^[^\s/\\]{1,255}$")

STATUS_UNVERIFIED = "unverified"
STATUS_VERIFIED = "verified"
STATUS_FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Platform:
    key: str
    label: str
    identifier: str  # ``account_id`` or ``username``
    description: str


PLATFORMS: dict[str, Platform] = {
    ATLASSIAN: Platform(ATLASSIAN, "Atlassian Cloud", ACCOUNT_ID,
                        "Your Atlassian account (Jira Cloud and Bitbucket Cloud) by its account id."),
    JIRA_SERVER: Platform(JIRA_SERVER, "Jira Server / Data Center", USERNAME, "Your Jira Server username."),
    BITBUCKET_SERVER: Platform(BITBUCKET_SERVER, "Bitbucket Server / Data Center", USERNAME,
                               "Your Bitbucket Server username."),
    GITHUB: Platform(GITHUB, "GitHub", USERNAME, "Your GitHub login."),
    GITLAB: Platform(GITLAB, "GitLab", USERNAME, "Your GitLab username."),
}


class LinkedAccountError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def platform(key: str) -> Platform:
    found = PLATFORMS.get(str(key or "").strip().lower())
    if found is None:
        raise LinkedAccountError("unknown_platform", f"Accounts are linked on: {', '.join(PLATFORMS)}.", 404)
    return found


def normalized_identifier(spec: Platform, value: str) -> str:
    """The account's identifier as stored, or a refusal naming what the platform expects."""
    text = str(value or "").strip()
    if spec.identifier == ACCOUNT_ID:
        if not ATLASSIAN_ACCOUNT_ID.fullmatch(text):
            raise LinkedAccountError("invalid_account_id", "An Atlassian account id is '<number>:<uuid>', 24 hex "
                                     "characters or '{<uuid>}' (Jira: Profile → the id in the address).")
        return text
    if not _USERNAME.fullmatch(text):
        raise LinkedAccountError("invalid_username", f"A {spec.label} username has no spaces or slashes.")
    return text


__all__ = ["ACCOUNT_ID", "ATLASSIAN", "ATLASSIAN_ACCOUNT_ID", "BITBUCKET_SERVER", "GITHUB", "GITLAB", "JIRA_SERVER",
           "LinkedAccountError", "PLATFORMS", "Platform", "STATUS_FAILED", "STATUS_UNVERIFIED", "STATUS_VERIFIED",
           "USERNAME", "normalized_identifier", "platform"]
