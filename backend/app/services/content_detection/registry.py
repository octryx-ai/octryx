"""The detector set a scan runs for a Workspace.

The built-in detectors always run; the custom detectors come from the policy-set version (published for live
decisions, the open draft for the draft shadow and the preview) and run only inside their scope (every
Workspace, or the one they name). Compiled programs are cached per definition.
"""

from __future__ import annotations

from functools import lru_cache

from .custom import CompiledCustomDetector, compile_detector
from .custom_definitions import CustomDetectorDefinition, DetectorDefinitions
from .scanner import DetectorSet
from .vocabulary import BUILTIN_DETECTOR_IDS


@lru_cache(maxsize=256)
def _compiled(definition: CustomDetectorDefinition) -> CompiledCustomDetector:
    return compile_detector(definition)


def detector_set_for(definitions: DetectorDefinitions, workspace_id: str | None) -> DetectorSet:
    workspace = str(workspace_id or "")
    custom = tuple(_compiled(item) for item in definitions.detectors
                   if not item.workspace_id or item.workspace_id == workspace)
    return DetectorSet(BUILTIN_DETECTOR_IDS, custom, definitions.digest() if not definitions.empty else "")


def combined_definitions(*sets: DetectorDefinitions) -> DetectorDefinitions:
    """The union of several versions' definitions (published + draft): the first one wins on a shared id."""
    detectors: dict[str, CustomDetectorDefinition] = {}
    categories = {}
    for item in sets:
        for detector in item.detectors:
            detectors.setdefault(detector.id, detector)
        for category in item.categories:
            categories.setdefault(category.id, category)
    return DetectorDefinitions(tuple(sorted(detectors.values(), key=lambda value: value.id)),
                               tuple(sorted(categories.values(), key=lambda value: value.id)))


__all__ = ["combined_definitions", "detector_set_for"]
