"""All skill catalog routers, mounted with one line in ``http_setup``."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    skill_catalog_assignment,
    skill_catalog_categories,
    skill_catalog_import,
    skill_catalog_skills,
    skill_catalog_upstream,
    skill_catalog_usage,
)

router = APIRouter()
for _module in (skill_catalog_categories, skill_catalog_import, skill_catalog_skills, skill_catalog_upstream,
                skill_catalog_assignment, skill_catalog_usage):
    router.include_router(_module.router)

__all__ = ["router"]
