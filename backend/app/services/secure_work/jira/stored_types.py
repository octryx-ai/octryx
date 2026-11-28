"""The Jira details a synced Work item stores in its ``source_fields_json``."""

from typing import Literal, TypedDict

StatusCategory = Literal["new", "indeterminate", "done"]
MappingSource = Literal["configured", "builtin", "status_category", "unmapped"]


class StoredJiraPerson(TypedDict):
    id: str  # the identifier filters match on
    display: str | None


class StoredJiraPeople(TypedDict):
    assignee: StoredJiraPerson | None
    reporter: StoredJiraPerson | None
    watchers: list[StoredJiraPerson]


class StoredJiraComment(TypedDict):
    id: str | None
    author: str | None
    author_display: str | None
    created: str | None
    body: str
    url: str | None


class StoredJiraDetails(TypedDict):
    people: StoredJiraPeople
    comments: list[StoredJiraComment]  # at most MAX_COMMENTS, the last ones in Jira's order
    comments_total: int | None


class StoredStatusMapping(TypedDict):
    source: MappingSource
    category: StatusCategory | None


__all__ = ["MappingSource", "StatusCategory", "StoredJiraComment", "StoredJiraDetails", "StoredJiraPeople",
           "StoredJiraPerson", "StoredStatusMapping"]
