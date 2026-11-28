"""Observability API: admin-only reads, one router per page. The only write is the audit event of a content read."""

from fastapi import APIRouter

from . import audit, decisions, health, runs, usage

router = APIRouter(prefix="/api/v1/observability", tags=["observability"])
router.include_router(runs.router)
router.include_router(decisions.router)
router.include_router(usage.router)
router.include_router(health.router)
router.include_router(audit.router)
# ``/metrics`` and the health probes stay at the root: runtime_endpoints.py; access in observability/endpoint_access.py.

__all__ = ["router"]
