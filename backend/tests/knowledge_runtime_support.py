from __future__ import annotations

from app.services.knowledge import runtime as _runtime
from app.services.knowledge.ledger.errors import EvidenceStoreUnavailableError
from app.services.knowledge.runtime import EvidenceRuntime


def set_evidence_runtime(runtime: EvidenceRuntime | None) -> None:
    if runtime is not None and type(runtime) is not EvidenceRuntime:
        raise EvidenceStoreUnavailableError()
    _runtime._RUNTIME = runtime
    _runtime._UNCONFIGURED = False
