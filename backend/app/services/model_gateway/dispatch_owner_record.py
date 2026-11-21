"""The record type and modes of the provider-dispatch owner inventory (:mod:`.dispatch_owners`).

The modes are described in the inventory's module documentation.
"""

from __future__ import annotations

from dataclasses import dataclass

DISPATCH_MODE_AUTHORITY = "authority"
DISPATCH_MODE_ADMITTED = "admitted"
DISPATCH_MODE_CATALOG_ONLY = "catalog_only"

DISPATCH_MODES = (DISPATCH_MODE_AUTHORITY, DISPATCH_MODE_ADMITTED, DISPATCH_MODE_CATALOG_ONLY)


@dataclass(frozen=True, slots=True)
class DispatchOwner:
    """One registered provider-dispatch owner.

    ``module`` is where the owner dispatches. ``boundary_module`` is set when the
    admission call itself was extracted into a focused module (the dispatching file
    being an oversized one); it is where the structural gate looks for the boundary
    call, and it counts as part of this owner for the "no unregistered dispatcher"
    rule.
    """

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
        """The module that must reach the admission boundary."""

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
