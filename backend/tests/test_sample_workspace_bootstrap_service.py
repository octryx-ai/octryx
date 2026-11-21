import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bootstrap import seed_database
from app.db import Base
from app.models import AgentDefinition, AgentStep, User
from app.services.sample_workspace_bootstrap import ensure_sample_workspace_bootstrap
from app.services.sample_workspace_bootstrap.sample_agents import DOCUMENT_UPDATER_DEFINITION


@pytest.fixture(scope="session")
def event_loop():
    import asyncio

    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'acme-orders-bootstrap.db'}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await seed_database(session)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_sample_workspace_bootstrap_creates_the_document_updater(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    existing_document_updater = (
        await db.execute(
            select(AgentDefinition).where(
                AgentDefinition.owner_id == admin.id,
                AgentDefinition.name == "Document Updater",
            )
        )
    ).scalar_one_or_none()
    if existing_document_updater is not None:
        await db.delete(existing_document_updater)
        await db.commit()

    await ensure_sample_workspace_bootstrap(db, admin_user=admin)
    await db.commit()

    agent = (
        await db.execute(
            select(AgentDefinition).where(
                AgentDefinition.owner_id == admin.id,
                AgentDefinition.name == "Document Updater",
            )
        )
    ).scalar_one()
    steps = (
        (await db.execute(select(AgentStep).where(AgentStep.agent_id == agent.id).order_by(AgentStep.position.asc())))
        .scalars()
        .all()
    )

    assert agent.description == DOCUMENT_UPDATER_DEFINITION["description"]
    assert agent.goal == DOCUMENT_UPDATER_DEFINITION["goal"]
    assert agent.agent_type == "change"
    assert agent.system_prompt == DOCUMENT_UPDATER_DEFINITION["system_prompt"]
    assert agent.output_prompt == DOCUMENT_UPDATER_DEFINITION["output_prompt"]
    assert [step.name for step in steps] == [step["name"] for step in DOCUMENT_UPDATER_DEFINITION["steps"]]
