"""The record type and modes of the provider-dispatch owner inventory (dispatch_owners)."""

from __future__ import annotations

from dataclasses import dataclass

DISPATCH_MODE_AUTHORITY = "authority"
DISPATCH_MODE_ADMITTED = "admitted"
DISPATCH_MODE_CATALOG_ONLY = "catalog_only"

DISPATCH_MODES = (DISPATCH_MODE_AUTHORITY, DISPATCH_MODE_ADMITTED, DISPATCH_MODE_CATALOG_ONLY)


@dataclass(frozen=True, slots=True)
class DispatchOwner:
    key: str
    category: str
    module: str
    mode: str
    boundary_module: str = ""

    @property
    def requires_admission(self) -> bool:
        return self.mode == DISPATCH_MODE_ADMITTED

    @property
    def admission_module(self) -> str:
        return self.boundary_module or self.module

    @property
    def modules(self) -> tuple[str, ...]:
        if self.boundary_module:
            return (self.module, self.boundary_module)
        return (self.module,)


__all__ = [
    "DISPATCH_MODES",
    "DISPATCH_MODE_ADMITTED",
    "DISPATCH_MODE_AUTHORITY",
    "DISPATCH_MODE_CATALOG_ONLY",
    "DispatchOwner",
]
