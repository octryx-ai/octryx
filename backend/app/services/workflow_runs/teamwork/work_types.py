"""The shape of ``context.work``, the run's current split. The device executor and the board build against it, so a
change here goes together with them."""

from typing import Literal, NotRequired, TypedDict

ItemStatus = Literal["pending", "running", "done", "merged", "failed", "blocked", "conflict"]
ExecutorName = Literal["device", "sequential"]
Route = Literal["done", "replan"]
ResultValue = Literal["done", "blocked"]
FixSource = Literal["pipeline", "review"]


class ItemResult(TypedDict):
    value: ResultValue
    summary: str


class SplitItem(TypedDict):
    id: str
    title: str
    role: str
    model: str | None
    depends_on: list[str]
    paths: list[str]
    appends_to: NotRequired[list[str]]
    instructions: str
    proofs: list[str]
    # pending -> running (once every depends_on item is merged) -> done -> merged; running can also end failed or
    # blocked, and done ends conflict when its merge conflicted.
    status: ItemStatus
    iteration: int  # a revision that reopens the item counts up; the item's own session resumes
    attempts: int  # starts in this iteration: a transient failure retries once
    session_id: str | None
    branch: str | None
    path: str | None
    base: str | None
    # runtime_target_id on the server; agent_hash and job_id on a device.
    runtime_target_id: str | None
    agent_hash: str | None
    job_id: str | None
    result: ItemResult | None
    reason: str | None
    # Set once a start was refused (the same session starts again at retry_at) or its folder could not be prepared.
    start_refusals: NotRequired[int]
    retry_at: NotRequired[str | None]
    start_detail: NotRequired[str | None]
    conflicts: list[str] | None
    merged_sha: str | None
    started_at: str | None
    finished_at: str | None
    merged_at: str | None
    # Set when a red pipeline or review findings reopen a merged item.
    fix: NotRequired[list[dict[str, str]] | None]
    fix_source: NotRequired[FixSource | None]


class WorkSplit(TypedDict):
    node_id: str
    plan_node: str
    plan_version: int
    plan_hash: str
    contract: str
    coordinator_session_id: NotRequired[str | None]
    coordinator_hash: NotRequired[str | None]  # only a device session has a board address
    executor: ExecutorName
    route: Route | None  # None until the node resolved
    updated_at: str
    items: dict[str, SplitItem]
    fixed_pipeline: NotRequired[str | None]
    fixed_review: NotRequired[int]


__all__ = ["ExecutorName", "FixSource", "ItemResult", "ItemStatus", "ResultValue", "Route", "SplitItem", "WorkSplit"]
