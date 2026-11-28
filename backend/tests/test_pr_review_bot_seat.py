"""PR review bot: whose seat reviews (the PR author's seat, then the company); the seat is opt-in per person
and Workspace."""

from __future__ import annotations

import pytest

from app.models import UserDevice, WorkflowRun, WorkflowRunEvent
from app.models.security.linked_account import UserLinkedAccount
from app.services.pr_review_bot import seat_choice
from app.services.pr_review_bot.render import build_post
from app.services.workflow_runs.review import choice, seat, seat_person
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace

PR = {"repository": "github:octryx-ai/review-bot-test", "pr_id": "2", "author": "Octryx-AI"}


def _run(project_id: str, requested_by: str, *, bot: bool = True, facts: dict | None = None) -> WorkflowRun:
    return WorkflowRun(project_id=project_id, workflow_kind="phased", title="t", requested_by=requested_by,
                       workflow_key="pr-review-bot" if bot else "review-and-pr", repository=PR["repository"],
                       branch="feature/x", context={"pr_review": facts if facts is not None else PR})


async def _people(db):
    workspace = await seed_workspace(db)
    admin = await seed_member(db, workspace_id=workspace, role="admin")
    member = await seed_member(db, workspace_id=workspace, role="member")
    bot = await seed_member(db, workspace_id=workspace, role="viewer")
    return workspace, admin, member, bot


async def test_the_review_seat_is_on_for_admins_off_for_members_and_a_choice_wins(db):
    workspace, admin, member, _bot = await _people(db)
    outsider = await seed_member(db, workspace_id=await seed_workspace(db), role="admin")
    assert (await seat_choice.review_seat_on(db, workspace, admin), await seat_choice.review_seat_on(
        db, workspace, member)) == (True, False)
    assert await seat_choice.review_seat_on(db, workspace, outsider) is False  # not a member: never
    from app.models import Project

    project = await db.get(Project, workspace)
    await seat_choice.set_review_seat(db, project, admin, False)
    await seat_choice.set_review_seat(db, project, member, True)
    assert (await seat_choice.review_seat_on(db, workspace, admin), await seat_choice.review_seat_on(
        db, workspace, member)) == (False, True)


async def test_the_pull_requests_author_is_found_by_the_linked_account_and_the_seat_opt_in(db):
    workspace, admin, member, bot = await _people(db)
    db.add(UserLinkedAccount(user_id=admin, platform="github", username="octryx-ai"))
    db.add(UserLinkedAccount(user_id=member, platform="atlassian", account_id="557058:anna"))
    await db.flush()
    run = _run(workspace, bot)
    person, source = await seat_person.seat_person(db, run)
    assert (person.id, source) == (admin, "pr_author")  # the login matches case-insensitively
    cloud = _run(workspace, bot, facts={"repository": "bitbucket:acme/payments", "author": "Anna Dev",
                                        "author_id": "557058:anna"})
    assert (await seat_person.seat_person(db, cloud))[0] is None  # Anna's seat is off (a member, no choice)
    from app.models import Project

    await seat_choice.set_review_seat(db, await db.get(Project, workspace), member, True)
    assert (await seat_person.seat_person(db, cloud))[0].id == member
    person, source = await seat_person.seat_person(db, _run(workspace, member, bot=False))
    assert (person.id, source) == (member, "requester")  # a person's own run keeps their seat


def test_a_bot_run_reviews_on_a_seat_first(db):
    assert choice.run_route(_run("ws", "bot")) == "seat"
    assert choice.run_route(_run("ws", "bot", bot=False)) == "company"


@pytest.fixture
def reachable(monkeypatch):
    from app.services.devices import hub, seat_quota
    from app.services.workflow_runs.runtime_target import auto

    monkeypatch.setattr(hub.device_hub, "reachable", lambda device: True)

    async def no_limit(*_args, **_kwargs):
        return None

    async def not_exhausted(*_args, **_kwargs):
        return False

    monkeypatch.setattr(seat_quota, "seat_limited_until", no_limit)
    monkeypatch.setattr(auto, "seat_exhausted", not_exhausted)


async def test_a_seat_review_takes_any_seat_device_of_the_person_without_a_known_folder(db, reachable):
    workspace, admin, _member, bot = await _people(db)
    from app.models import User

    device = UserDevice(owner_user_id=admin, name="MacBook", name_key="macbook", os="macos", public_key="k",
                        folders=["/Users/dev/code"], profiles=["seat", "default"])
    db.add(device)
    await db.flush()
    person = await db.get(User, admin)
    found = await seat.seat_device(db, _run(workspace, bot), user=person, review_call=True)
    assert found == (device, "/Users/dev/code")  # no run of this repository ever ran there: still a seat
    # A turn with tools never gets a device without a known folder of the repository.
    assert await seat.seat_device(db, _run(workspace, bot), user=person) == "seat_no_device"


async def test_the_seat_turn_and_thread_are_the_seat_persons_and_the_event_says_whose(db, reachable, monkeypatch):
    workspace, admin, _member, bot = await _people(db)
    device = UserDevice(owner_user_id=admin, name="MacBook", name_key="macbook", os="macos", public_key="k",
                        folders=["/Users/dev/code"], profiles=["seat"])
    run = _run(workspace, bot)
    db.add_all([device, run])
    await db.flush()
    asked = []

    async def refused(db_, *, user_id, session_id, **_kwargs):
        from app.models import Session

        asked.append((user_id, (await db_.get(Session, session_id)).user_id))
        return type("Refused", (), {"reason": "device_busy"})()

    monkeypatch.setattr("app.services.devices.chat_turn.start_device_turn", refused)
    model = seat.SeatReviewModel(db, run, choice.ReviewChoice("claude_code", "claude-haiku-5-5", "seat", "p", "r"),
                                 device, "/Users/dev/code", person_id=admin, source="pr_author")
    with pytest.raises(seat.SeatReviewUnavailableError):
        await model.answer(system="s", user="u")
    assert asked == [(admin, admin)]  # the dispatch gate needs the device's owner to own the turn and its thread
    from sqlalchemy import select

    detail = (await db.execute(select(WorkflowRunEvent.detail).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == seat.EVENT_SEAT_SESSION))).scalar_one()
    assert (detail["seat_user_id"], detail["seat_source"]) == (admin, "pr_author")


def test_the_summary_names_whose_seat_reviewed():
    post = build_post({"verdict": "pass", "summary": "ok", "findings": []}, {}, provider="github", facts={
        "sha": "c0ffee00", "model": "claude-haiku-5-5", "route": "seat", "seat_of": "Alice Example"})
    assert "reviewer claude-haiku-5-5 (Alice Example's seat)" in post.summary


async def test_the_team_is_asked_first_and_the_author_after_without_the_bot(db):
    workspace, admin, member, bot = await _people(db)
    other_admin = await seed_member(db, workspace_id=workspace, role="admin")
    db.add(UserLinkedAccount(user_id=admin, platform="github", username="octryx-ai"))
    await db.flush()
    phases = await seat_choice.bot_seat_phases(db, _run(workspace, bot))
    assert [[(person.user.id, person.source) for person in phase] for phase in phases] == [
        [(other_admin, "broadcast")], [(admin, "pr_author")]]  # the member's seat is off; never the bot


class _Seat:
    def __init__(self, db, owner, device, session):
        self.db, self.owner, self.device, self.session = db, owner, device, session
        self.job, self.finished, self.answered = None, 0, 0

    async def start(self, *, system, user, images=None):
        from app.models import DeviceJob

        self.job = DeviceJob(device_id=self.device, owner_user_id=self.owner, session_id=self.session.id,
                             folder="/f", profile="seat", status="offered", turn_state="pending", turn_id="t")
        self.session.metadata_ = {seat.REQUEST_KEY: {"turn_id": "t"}}
        self.db.add(self.job)
        await self.db.flush()
        return self.job, self.session

    async def finish(self, job, thread):
        self.finished += 1
        return "answer"

    async def answer(self, *, system, user, images=None):
        self.answered += 1
        return "again"


async def _candidates(db, workspace, people):
    from app.models import Session

    seats = []
    for person in people:
        device = UserDevice(owner_user_id=person, name=f"d{person[:4]}", name_key=f"d{person[:4]}", os="macos",
                            public_key="k", folders=["/f"], profiles=["seat"])
        session = Session(user_id=person, project_id=workspace, status="active", origin="chat", metadata_={})
        db.add_all([device, session])
        await db.flush()
        seats.append(_Seat(db, person, device.id, session))
    return seats


async def test_the_first_device_that_takes_the_offer_reviews_and_the_others_are_withdrawn(db):
    from app.services.workflow_runs.review.seat_broadcast import EVENT_BROADCAST, BroadcastSeatReviewModel

    workspace, admin, member, bot = await _people(db)
    run = _run(workspace, bot)
    db.add(run)
    await db.flush()
    first, second = await _candidates(db, workspace, [admin, member])

    async def tick(_seconds):
        second.job.turn_state, second.job.status = "accepted", "running"  # the second device takes it
        await db.flush()  # as the device's job_accepted event writes it

    model = BroadcastSeatReviewModel(db, run, [[first, second]], sleep=tick)
    assert await model.answer(system="s", user="u") == "answer" and second.finished == 1
    assert (first.job.turn_state, first.job.status) == ("cancelled", "idle")  # withdrawn: the slot is free again
    assert seat.REQUEST_KEY not in (first.session.metadata_ or {})
    assert await model.answer(system="s", user="again") == "again" and second.answered == 1  # sticky winner
    from sqlalchemy import select

    detail = (await db.execute(select(WorkflowRunEvent.detail).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == EVENT_BROADCAST))).scalar_one()
    assert (sorted(detail["offered_to"]), detail["taken_by"]) == (sorted([admin, member]), member)


async def test_nobody_takes_the_team_offer_then_the_author_and_else_no_seat(db):
    from app.services.workflow_runs.review.seat_broadcast import BroadcastSeatReviewModel

    workspace, admin, member, bot = await _people(db)
    run = _run(workspace, bot)
    db.add(run)
    await db.flush()
    team, author = await _candidates(db, workspace, [member, admin])
    now = [0.0]

    async def tick(_seconds):
        now[0] += 60
        if author.job is not None:
            author.job.turn_state = "accepted"
            await db.flush()

    model = BroadcastSeatReviewModel(db, run, [[team], [author]], sleep=tick, clock=lambda: now[0],
                                     accept_seconds=90)
    assert await model.answer(system="s", user="u") == "answer" and author.finished == 1
    assert team.job.turn_state == "cancelled"  # the team's offer timed out and was withdrawn
    nobody = BroadcastSeatReviewModel(db, run, [[(await _candidates(db, workspace, [member]))[0]]],
                                      sleep=tick, clock=lambda: now[0], accept_seconds=90)
    with pytest.raises(seat.SeatReviewUnavailableError):  # the caller then takes the visible company fallback
        await nobody.answer(system="s", user="u")


async def test_the_footer_names_the_person_by_the_pull_requests_login(db):
    workspace, admin, _member, _bot = await _people(db)
    assert (await seat_choice.seat_login(db, admin, "github:octryx-ai/review-bot-test")).startswith("member")
    db.add(UserLinkedAccount(user_id=admin, platform="github", username="octryx-ai"))
    await db.flush()
    assert await seat_choice.seat_login(db, admin, "github:octryx-ai/review-bot-test") == "octryx-ai"
