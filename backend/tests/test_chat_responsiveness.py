import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.models import Session, User
from app.services.session.run_state import RUN_STATUS_IN_PROGRESS, set_session_run_state


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_parallel_bootstrap_polls_keep_running_session_lightweight(client, auth_headers, db):
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(
        id=str(uuid.uuid4()),
        user_id=admin_user.id,
        agent_type="coding",
        status="active",
        metadata_={"title": "Parallel responsiveness probe"},
    )
    set_session_run_state(session, RUN_STATUS_IN_PROGRESS)
    db.add(session)
    await db.commit()

    async def fetch_bootstrap():
        return await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}", headers=auth_headers)

    responses = await asyncio.gather(*(fetch_bootstrap() for _ in range(8)))

    assert all(response.status_code == 200 for response in responses)
    assert {response.headers.get("X-Chat-Bootstrap-Kind") for response in responses} == {"running_ack"}
    elapsed_values = [int(response.headers["X-Chat-Bootstrap-Elapsed-Ms"]) for response in responses]
    payload_sizes = [int(response.headers["X-Chat-Bootstrap-Payload-Bytes"]) for response in responses]
    assert max(elapsed_values) >= 0
    assert max(payload_sizes) < 50_000
    assert all(response.json()["selectedSessionIsRunning"] is True for response in responses)
