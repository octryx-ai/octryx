"""The classification level registry: admins may add levels.

A level is a row of ``data_classification_levels``: an immutable ``key``, a stored ``rank`` (gapped: the built-ins sit
at 100 … 500, a new level takes a free rank between its neighbours, so inserting a level never shifts the rank of an
existing one — decision logs, saved test cases and custom policies keep meaning what they meant), a label, a colour
key, a description and whether any model may process data of the level. Built-in levels can be relabelled, never
retired; a custom level is retired (never deleted) and only while nothing uses it.

Every reader goes through one process-wide :class:`LevelRegistry`: ``model_gateway.data_policy.classification`` exposes
the order, the vocabulary and the ranks from it (``DATA_CLASSIFICATION_ORDER`` and ``DATA_CLASSIFICATION_LEVELS`` are
live views), so no module keeps its own list. The registry is loaded from the table at start-up and refreshed by
:func:`ensure_level_registry` (cheap; called where the classification policy is loaded) and right after a publish.
Until the table is read, and when it cannot be read, the built-ins apply — they are exactly the original levels.

A governed draft that adds a level is checked under that draft's registry (:func:`candidate_registry`), never by
changing the live one.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
LEVEL_COLORS: tuple[str, ...] = ("custom", "public", "internal", "confidential", "restricted", "secret")
RANK_STEP = 100
REFRESH_SECONDS = 30.0
MAX_LABEL = 60
MAX_DESCRIPTION = 300


@dataclass(frozen=True, slots=True)
class LevelDef:
    key: str
    rank: int
    label: str
    color: str = "custom"
    description: str = ""
    models_allowed: bool = True
    builtin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BUILTIN_LEVELS: tuple[LevelDef, ...] = (
    LevelDef("public", 100, "Public", "public", "May be published.", True, True),
    LevelDef("internal", 200, "Internal", "internal", "For everyone in the company.", True, True),
    LevelDef("confidential", 300, "Confidential", "confidential", "Named teams only.", True, True),
    LevelDef("restricted", 400, "Restricted", "restricted", "Need-to-know; regulated data.", True, True),
    LevelDef("secret", 500, "Secret", "secret", "No model may process it.", False, True),
)


class LevelRegistry:
    """An ordered, immutable set of levels (ascending rank)."""

    def __init__(self, levels: Sequence[LevelDef]) -> None:
        ordered = tuple(sorted(levels, key=lambda level: level.rank))
        self.levels = ordered
        self.order: tuple[str, ...] = tuple(level.key for level in ordered)
        self._by_key = {level.key: level for level in ordered}
        self._by_rank = {level.rank: level for level in ordered}

    def get(self, key: Any) -> LevelDef | None:
        return self._by_key.get(str(key or "").strip().lower())

    def rank(self, key: Any) -> int | None:
        level = self.get(key)
        return level.rank if level is not None else None

    def at_rank(self, rank: Any) -> LevelDef | None:
        try:
            return self._by_rank.get(int(rank))
        except (TypeError, ValueError):
            return None

    def model_levels(self) -> tuple[str, ...]:
        """The levels a model may be cleared for (a gateway alias's data-policy class)."""
        return tuple(level.key for level in self.levels if level.models_allowed)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self._by_key

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LevelRegistry) and self.levels == other.levels

    def __hash__(self) -> int:
        return hash(self.levels)


BUILTIN_REGISTRY = LevelRegistry(BUILTIN_LEVELS)
_live: LevelRegistry = BUILTIN_REGISTRY
_loaded_at = 0.0
_candidate: ContextVar[LevelRegistry | None] = ContextVar("classification_level_candidate", default=None)


def level_registry() -> LevelRegistry:
    """The registry in effect: a draft's candidate while it is checked, else the live one."""
    return _candidate.get() or _live


def set_level_registry(registry: LevelRegistry) -> None:
    global _live, _loaded_at
    _live, _loaded_at = registry, time.monotonic()


def reset_level_registry() -> None:
    """Back to the built-ins (tests)."""
    global _live, _loaded_at
    _live, _loaded_at = BUILTIN_REGISTRY, 0.0


@contextmanager
def candidate_registry(registry: LevelRegistry) -> Iterator[None]:
    token = _candidate.set(registry)
    try:
        yield
    finally:
        _candidate.reset(token)


def registry_from_rows(rows: Sequence[Any]) -> LevelRegistry:
    """Active rows of ``data_classification_levels`` (empty → the built-ins)."""
    levels = [
        LevelDef(str(row.key), int(row.rank), str(row.label), str(row.color or "custom"), str(row.description or ""),
                 bool(row.models_allowed), bool(row.builtin))
        for row in rows if getattr(row, "retired_at", None) is None
    ]
    return LevelRegistry(levels) if levels else BUILTIN_REGISTRY


async def refresh_level_registry(db: Any) -> LevelRegistry:
    """Load the live registry from the table; on any failure keep the current one."""
    from sqlalchemy import select

    from ...models import DataClassificationLevel

    try:
        rows = (await db.execute(select(DataClassificationLevel))).scalars().all()
    except Exception:  # noqa: BLE001 - an unreadable table must never break a decision; the last registry stays
        logger.warning("classification_level_registry_unreadable", exc_info=True)
        return _live
    registry = registry_from_rows(rows)
    set_level_registry(registry)
    from .effect_rules import refresh_effect_rules

    await refresh_effect_rules(db)  # the added rules are published with the levels
    return registry


async def ensure_level_registry(db: Any) -> LevelRegistry:
    """Refresh when older than :data:`REFRESH_SECONDS` (other workers may have published)."""
    if time.monotonic() - _loaded_at >= REFRESH_SECONDS:
        return await refresh_level_registry(db)
    return _live


# --- the catalog inside a governed draft ---------------------------------------------------------------------------

ERROR_LEVEL_KEY_INVALID = "classification_level_key_invalid"
ERROR_LEVEL_KEY_DUPLICATE = "classification_level_key_duplicate"
ERROR_LEVEL_RANK_INVALID = "classification_level_rank_invalid"
ERROR_LEVEL_LABEL_INVALID = "classification_level_label_invalid"
ERROR_LEVEL_COLOR_INVALID = "classification_level_color_invalid"
ERROR_BUILTIN_CHANGED = "classification_level_builtin_changed"
ERROR_LEVEL_RANK_CHANGED = "classification_level_rank_changed"
ERROR_LEVEL_IN_USE = "classification_level_in_use"


class LevelCatalogError(ValueError):
    def __init__(self, code: str, path: str, **details: Any) -> None:
        super().__init__(f"{path}: {code}")
        self.code = code
        self.path = path
        self.details = details


def catalog_of(registry: LevelRegistry) -> list[dict[str, Any]]:
    return [level.to_dict() for level in registry.levels]


def normalized_catalog(raw: Any, *, base: LevelRegistry) -> LevelRegistry:
    """Validate a submitted level catalog against ``base`` (the published one).

    Keys are immutable and unique; an existing level keeps its rank; a built-in keeps its key, rank and model switch
    and is never left out; a new level takes a rank no other level holds. Leaving a custom level out retires it.
    """
    if not isinstance(raw, list):
        raise LevelCatalogError(ERROR_LEVEL_KEY_INVALID, "level_catalog")
    seen: set[str] = set()
    ranks: set[int] = set()
    levels: list[LevelDef] = []
    for index, item in enumerate(raw):
        path = f"level_catalog[{index}]"
        if not isinstance(item, Mapping):
            raise LevelCatalogError(ERROR_LEVEL_KEY_INVALID, path)
        key = str(item.get("key") or "")
        if not KEY_PATTERN.match(key):
            raise LevelCatalogError(ERROR_LEVEL_KEY_INVALID, f"{path}.key")
        if key in seen:
            raise LevelCatalogError(ERROR_LEVEL_KEY_DUPLICATE, f"{path}.key")
        rank = item.get("rank")
        if type(rank) is not int or not 1 <= rank <= 1_000_000 or rank in ranks:
            raise LevelCatalogError(ERROR_LEVEL_RANK_INVALID, f"{path}.rank")
        label = str(item.get("label") or "").strip()
        if not label or len(label) > MAX_LABEL:
            raise LevelCatalogError(ERROR_LEVEL_LABEL_INVALID, f"{path}.label")
        color = str(item.get("color") or "custom")
        if color not in LEVEL_COLORS:
            raise LevelCatalogError(ERROR_LEVEL_COLOR_INVALID, f"{path}.color")
        existing = base.get(key)
        builtin = existing.builtin if existing is not None else False
        models_allowed = item.get("models_allowed", True) is not False
        if existing is not None and existing.rank != rank:
            raise LevelCatalogError(ERROR_LEVEL_RANK_CHANGED, f"{path}.rank")
        if builtin and models_allowed != existing.models_allowed:
            raise LevelCatalogError(ERROR_BUILTIN_CHANGED, f"{path}.models_allowed")
        seen.add(key)
        ranks.add(rank)
        levels.append(LevelDef(key, rank, label, color, str(item.get("description") or "").strip()[:MAX_DESCRIPTION],
                               models_allowed, builtin))
    missing = [level.key for level in base.levels if level.builtin and level.key not in seen]
    if missing:
        raise LevelCatalogError(ERROR_BUILTIN_CHANGED, "level_catalog", missing=missing)
    return LevelRegistry(levels)


def rank_between(lower: LevelDef | None, upper: LevelDef | None) -> int | None:
    """A free rank between two neighbours (``None`` when no integer fits)."""
    if lower is None and upper is None:
        return RANK_STEP
    if upper is None:
        return lower.rank + RANK_STEP  # type: ignore[union-attr]
    if lower is None:
        return upper.rank // 2 if upper.rank > 1 else None
    middle = (lower.rank + upper.rank) // 2
    return middle if lower.rank < middle < upper.rank else None


__all__ = [
    "BUILTIN_LEVELS",
    "BUILTIN_REGISTRY",
    "ERROR_LEVEL_IN_USE",
    "KEY_PATTERN",
    "LEVEL_COLORS",
    "LevelCatalogError",
    "LevelDef",
    "LevelRegistry",
    "candidate_registry",
    "catalog_of",
    "ensure_level_registry",
    "level_registry",
    "normalized_catalog",
    "rank_between",
    "refresh_level_registry",
    "registry_from_rows",
    "reset_level_registry",
    "set_level_registry",
]
