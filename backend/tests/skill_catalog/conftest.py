"""Fixtures of the skill catalog tests."""

import pytest_asyncio
from sqlalchemy import select

from app.models import Skill, User
from tests.skill_catalog.fake_git import fake_git  # noqa: F401 - fixture for the whole package
from tests.skill_catalog.support import publish_chat_skill

# Two published chat skills in the "diagnosis" category.
CHAT_SKILLS = (
    ("alert-diagnosis", "Analyze active Grafana Alert and determine root cause"),
    ("cluster-health", "Run comprehensive cluster health analysis"),
)


@pytest_asyncio.fixture
async def chat_skills(db):
    """Two published chat-only skills (``alert-diagnosis``, ``cluster-health``)."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    for name, desc in CHAT_SKILLS:
        if (await db.execute(select(Skill).where(Skill.name == name))).scalar_one_or_none() is not None:
            continue
        await publish_chat_skill(db, name, approver_id=admin.id, description=desc, category="diagnosis",
                                 body=f"# {name}\n\n{desc}", when_to_use=f"Use for {name} in diagnosis.",
                                 allowed_roles=("admin", "operator", "viewer"), executor_type="llm_interpret")
    await db.flush()
