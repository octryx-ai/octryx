"""Server side: bundle scan, attachments, the client handoff control plane, handoff_now."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import WorkItemHandoffAttachment
from app.services.agent_board import handoff_attachments
from app.services.agent_board.bundle_scan import scan_bundle
from tests.agent_board.client_handoff_support import AWS_KEY, BASE, _bundle, _headers, board, store  # noqa: F401
from tests.agent_gateway.seat_presence_support import _gateway_headers
from tests.knowledge_evidence_seed_support import seed_member


async def _other_workspace(db) -> str:
    from tests.agent_gateway.seat_presence_support import _workspace

    return await _workspace(db)


async def _workspace_of(db, user_id) -> str:
    from app.models.security.user import UserProject

    return (await db.execute(select(UserProject.project_id).where(UserProject.user_id == user_id))).scalar_one()


# --- bundle scan --------------------------------------------------------------------------------------------


def test_the_bundle_scan_inflates_the_pack_and_finds_secrets(tmp_path):
    clean = _bundle(tmp_path / "a", {"app.py": "print('hello')\n"})
    secret = _bundle(tmp_path / "b", {"app.py": "x = 1\n", "notes.txt": f"key {AWS_KEY}\n"})
    assert scan_bundle(clean) == ""
    assert scan_bundle(secret) == "secret_detected"
    assert AWS_KEY.encode() not in secret  # the raw bytes alone would never show it
    assert scan_bundle(b"junk") == scan_bundle(clean[:-30]) == scan_bundle(b"# v2 git bundle\n\nXXXX") == \
        "bundle_invalid"
    assert scan_bundle(b"# v9 git bundle\n" + clean.split(b"\n", 1)[1]) == "bundle_invalid"  # unknown format


@pytest.mark.asyncio
async def test_a_bundle_is_stored_in_parts_scanned_and_read_back_by_members(client, db, board, store, tmp_path,  # noqa: F811
                                                                            monkeypatch):
    monkeypatch.setattr(handoff_attachments, "PART_BYTES", 256)
    data = _bundle(tmp_path, {f"f{n}.txt": f"content {n}\n" * 20 for n in range(5)})
    headers = await _headers(db, board)

    stored = await client.post(f"{BASE}/attachments", params={"work_item_id": "BRD-6"}, content=data,
                               headers=headers)
    body = stored.json()
    row = await db.get(WorkItemHandoffAttachment, body["bundle_id"])
    read = await client.get(f"{BASE}/attachments/{body['bundle_id']}",
                            headers=await _headers(db, board, board.ben, board.ben_key))

    assert stored.status_code == 200 and body["byte_size"] == len(data)
    assert len(row.parts) == -(-len(data) // 256) and row.work_item_id == board.item.id
    assert read.status_code == 200 and read.content == data and read.headers["x-octryx-sha256"] == row.sha256
    stranger = await seed_member(db, workspace_id=(await _other_workspace(db)), role="member")
    await db.commit()
    outside = await client.get(f"{BASE}/attachments/{body['bundle_id']}",
                               headers=await _gateway_headers(db, stranger, await _workspace_of(db, stranger)))
    assert outside.status_code == 404


@pytest.mark.asyncio
async def test_a_secret_or_oversized_bundle_is_refused_and_nothing_is_stored(client, db, board, store, tmp_path,  # noqa: F811
                                                                             monkeypatch):
    secret = _bundle(tmp_path / "s", {"x.txt": f"{AWS_KEY}\n"})
    headers = await _headers(db, board)
    refused = await client.post(f"{BASE}/attachments", params={"work_item_id": "BRD-6"}, content=secret,
                                headers=headers)
    monkeypatch.setattr(handoff_attachments, "MAX_ATTACHMENT_BYTES", 10)
    large = await client.post(f"{BASE}/attachments", params={"work_item_id": "BRD-6"},
                              content=_bundle(tmp_path / "c", {"a": "b\n"}), headers=headers)
    assert refused.status_code == 422 and refused.json()["detail"] == {"code": "secret_detected"}
    assert AWS_KEY not in refused.text and large.status_code == 413
    assert store.objects == {} and store.puts == []
    assert (await db.execute(select(func.count(WorkItemHandoffAttachment.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_an_unconfigured_store_is_a_coded_409(client, db, board, tmp_path, monkeypatch):  # noqa: F811
    def unconfigured():
        raise RuntimeError("not configured")

    monkeypatch.setattr(handoff_attachments, "attachment_store", unconfigured)
    answer = await client.post(f"{BASE}/attachments", params={"work_item_id": "BRD-6"},
                               content=_bundle(tmp_path, {"a": "b\n"}), headers=await _headers(db, board))
    assert answer.status_code == 409 and answer.json()["detail"] == {"code": "attachment_store_not_configured"}


# --- UI: bundle download -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_members_download_a_handoff_bundle_with_their_login(client, db, board, store, tmp_path):  # noqa: F811
    from tests.agent_board.board_rest_support import _get

    data = _bundle(tmp_path, {"a.py": "x = 1\n"})
    bundle_id = (await client.post(f"{BASE}/attachments", params={"work_item_id": "BRD-6"}, content=data,
                                   headers=await _headers(db, board))).json()["bundle_id"]
    member = await _get(client, f"/handoff-attachments/{bundle_id}", board.ben)
    outsider = await _get(client, f"/handoff-attachments/{bundle_id}", board.outsider)
    missing = await _get(client, "/handoff-attachments/nope", board.ben)
    assert member.status_code == 200 and member.content == data
    assert member.headers["content-disposition"].endswith('.bundle"')
    assert (outsider.status_code, missing.status_code) == (404, 404)
