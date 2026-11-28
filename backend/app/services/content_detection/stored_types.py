"""The JSON content detection stores: a scan's summary in a decision record's ``content`` field and the custom
detector set of a policy-set version."""

from typing import Literal, NotRequired, TypedDict

Confidence = Literal["high", "medium"]
CustomCheck = Literal["none", "mod10", "mod97"]
CustomMaskStyle = Literal["type_token", "last4", "full"]


class DetectedCount(TypedDict):
    id: str
    count: int
    confidence: Confidence  # the highest of the detector's findings


class ScanSummary(TypedDict):
    detected: list[DetectedCount]
    categories: list[str]
    findings: int
    sources: list[str]
    complete: bool
    scanned_bytes: int
    scan_us: int
    kinds: NotRequired[list[str]]  # the secret scanner's fixed kinds, when it found any
    unfinished: NotRequired[bool]  # present only when true
    unreadable: NotRequired[bool]  # present only when true


class StoredCategory(TypedDict):
    id: str
    label: str


class StoredCustomDetector(TypedDict):
    id: str  # custom.<slug>
    label: str
    category: str
    pattern: str
    check: CustomCheck
    context_words: list[str]
    mask_style: CustomMaskStyle
    workspace_id: str | None  # None: every Workspace


class StoredDetectorSet(TypedDict):
    categories: list[StoredCategory]
    detectors: list[StoredCustomDetector]


__all__ = [
    "Confidence",
    "CustomCheck",
    "CustomMaskStyle",
    "DetectedCount",
    "ScanSummary",
    "StoredCategory",
    "StoredCustomDetector",
    "StoredDetectorSet",
]
