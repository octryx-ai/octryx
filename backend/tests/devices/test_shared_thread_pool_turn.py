"""A shared thread's writer continues it on the runners as their own turn; a reader is refused as before."""

import uuid

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Project, Session, User
from app.models.session.session_collaboration import SessionCollaborator
from app.services.devices.agent_runtime import POOL_TARGET
from app.services.devices.chat_turn import DeviceTurnRefusal, DeviceTurnStarted, start_device_turn
from tests.chat_pool_support import chat_pool  # noqa: F401 - fixture


async def _person(db, role: str, session: Session) -> User:
    person = User(id=str(uuid.uuid4()), username=f"{role}-{uuid.uuid4().hex[:6]}", email=f"{role}@stub.test",
                  password_hash="x", is_active=True)
    db.add(person)
    await db.flush()
    db.add(SessionCollaborator(session_id=session.id, user_id=person.id, role=role, invited_by=session.user_id))
    await db.flush()
    return person


@pytest.mark.asyncio
async def test_a_contributor_continues_the_shared_thread_on_the_runners_and_an_observer_is_refused(
        db, chat_pool):  # noqa: F811
    owner = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    thread = Session(user_id=owner.id, project_id=project.id, status="active", metadata_={"title": "Shared"})
    db.add(thread)
    await db.flush()
    contributor, observer = await _person(db, "contributor", thread), await _person(db, "observer", thread)

    started = await start_device_turn(db, user_id=contributor.id, prompt="Next step, please.",
                                      target=dict(POOL_TARGET), session_id=thread.id)
    assert isinstance(started, DeviceTurnStarted), started
    job = await db.get(DeviceJob, started.job_id)
    assert (job.device_id, job.owner_user_id, job.session_id) == (chat_pool.id, contributor.id, thread.id)

    refused = await start_device_turn(db, user_id=observer.id, prompt="Me too.", target=dict(POOL_TARGET),
                                      session_id=thread.id)
    assert isinstance(refused, DeviceTurnRefusal) and (refused.reason, refused.status) == ("device_target_not_owner", 403)
