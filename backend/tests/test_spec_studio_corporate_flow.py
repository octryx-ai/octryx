"""The Corporate Identity in the Spec Studio: preselected, deviations need a reason and go into SPEC.md,
locked values are read-only, an approved version keeps its snapshot, a feature keeps the approved look."""

from __future__ import annotations

import pytest

from app.services.office_identity import build_corporate_identity
from app.services.workflow_runs.spec_studio import corporate_link
from tests import test_spec_studio_flow as flow
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.services.corp_identity.test_corp_identity_workspace import _profiles
from tests.test_spec_studio_corporate import _TEMPLATE

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.fixture
def brief(monkeypatch):
    calls: list[str] = []

    async def fake(_db, profile_id):
        calls.append(profile_id)
        return {**build_corporate_identity([_TEMPLATE]), "profile_id": profile_id, "profile_name": "Example Brand",
                "assets": {"logos": [{"path": "assets/logo.png"}], "icons": [{"path": "icons/general/cup.svg"}]}}

    monkeypatch.setattr("app.services.corp_identity.profile_edits.get_corp_identity_brief", fake)
    return calls


async def _studio_run(db, tmp_path):
    await _profiles(db, "house")
    return await flow._waiting_run(db, tmp_path)


def _url(run) -> str:
    return f"/api/v1/workflow-runs/{run.id}/spec-studio"


@pytest.mark.asyncio
async def test_the_company_look_is_preselected_and_the_specs_directions_are_the_alternatives(
        client, auth_headers, db, tmp_path, brief):
    run = await _studio_run(db, tmp_path)
    studio = (await client.get(_url(run), headers=auth_headers)).json()
    assert (studio["design"]["direction"], studio["design"]["name"]) == ("corporate", "Corporate: Example Brand")
    assert studio["design"]["light"]["accent"] == "#0B5FA5"
    corporate = studio["corporate"]
    assert (corporate["profile_id"], corporate["source"], corporate["logo"]) == ("house", "installation",
                                                                                  "assets/logo.png")
    assert corporate["sources"]["light.accent"] == "ci" and corporate["icons"] == {"cup": "icons/general/cup.svg"}
    assert studio["deviations"] == [] and studio["open_points"] == []
    await client.get(_url(run), headers=auth_headers)
    assert brief == ["house"]

    switched = (await client.patch(_url(run), headers=auth_headers, json={"op": "design", "direction": "crema"})).json()
    assert switched["deviations"] == [{"path": "direction", "corporate": "Corporate: Example Brand",
                                       "chosen": switched["design"]["name"], "reason": ""}]
    assert [p["by"] for p in switched["open_points"]] == ["product_owner"]


@pytest.mark.asyncio
async def test_a_changed_company_colour_needs_a_reason_and_spec_md_and_the_handoff_carry_it(
        client, auth_headers, db, tmp_path, brief):
    from app.services.workflow_runs.spec_studio.hooks import agent_open_points

    run = await _studio_run(db, tmp_path)
    changed = (await client.patch(_url(run), headers=auth_headers,
                                  json={"op": "design", "theme": "light", "key": "accent", "value": "#0A4F8A"})).json()
    assert changed["deviations"] == [{"path": "light.accent", "corporate": "#0B5FA5", "chosen": "#0A4F8A",
                                      "reason": ""}]
    assert changed["open_points"][0]["target"] == "deviation:light.accent"
    await db.refresh(run)
    assert agent_open_points(run) == []
    refused = await client.post(f"{_url(run)}/approve", headers=auth_headers)
    assert refused.status_code == 409 and "differs from Corporate" in refused.text

    await client.patch(_url(run), headers=auth_headers,
                       json={"op": "design", "theme": "dark", "key": "accent", "value": "#5AA0E0"})
    reasoned = await client.patch(_url(run), headers=auth_headers,
                                  json={"op": "reason", "path": "light.accent", "text": "AA on the new header."})
    assert reasoned.json()["open_points"] == []
    approved = await client.post(f"{_url(run)}/approve", headers=auth_headers)
    assert approved.status_code == 200, approved.text
    await db.refresh(run)
    entry = run.context["spec_studio"]["approved"][-1]
    assert entry["corporate"]["profile_id"] == "house" and entry["corporate"]["hash"]
    assert entry["deviations"] == [{"path": "light.accent", "corporate": "#0B5FA5", "chosen": "#0A4F8A",
                                    "reason": "AA on the new header."}]
    spec = (tmp_path / flow.SPEC).read_text(encoding="utf-8")
    assert "Corporate: Example Brand (the company's Corporate Identity)" in spec
    assert "Differs from Corporate (#0B5FA5), because: AA on the new header." in spec

    await _profiles(db, "other")
    brief.clear()
    await client.get(_url(run), headers=auth_headers)
    await db.refresh(run)
    assert brief == [] and run.context["spec_studio"]["corporate"]["profile_id"] == "house"


@pytest.mark.asyncio
async def test_locked_company_values_are_read_only(client, auth_headers, db, tmp_path, brief):
    run = await _studio_run(db, tmp_path)
    locks = await client.put("/admin/chat/api/panel/corp-identities/house/studio-locks", headers=auth_headers,
                             json={"paths": ["light.accent", "fonts.head"]})
    assert locks.status_code == 200
    studio = (await client.get(_url(run), headers=auth_headers)).json()
    assert studio["corporate"]["locks"] == ["fonts.head", "light.accent"]
    for change in ({"op": "design", "theme": "light", "key": "accent", "value": "#0A4F8A"},
                   {"op": "design", "font": {"head": "Comic Sans"}}, {"op": "design", "direction": "crema"}):
        locked = await client.patch(_url(run), headers=auth_headers, json=change)
        assert locked.status_code == 409 and locked.json()["detail"]["code"] == "locked_by_corporate"
    free = await client.patch(_url(run), headers=auth_headers,
                              json={"op": "design", "theme": "light", "key": "muted", "value": "#3A4558"})
    assert free.status_code == 200


@pytest.mark.asyncio
async def test_a_feature_keeps_the_approved_apps_look(db, tmp_path, brief, monkeypatch):
    run = await _studio_run(db, tmp_path)
    record = run.context["outputs"]["spec_studio"]
    monkeypatch.setattr("app.services.workflow_runs.spec_studio.service.base_of",
                        lambda _run, artefact: {"design": {}} if artefact.get("mode") == "feature" else None)
    assert corporate_link.snapshot(run) is not None
    newest = record[-1] if isinstance(record, list) else record
    newest["record"]["mode"] = "feature"
    assert await corporate_link.refresh(db, run) is True and corporate_link.snapshot(run) is None


@pytest.mark.asyncio
async def test_the_mock_gets_the_ci_logo_and_icons_but_no_other_file(client, auth_headers, db, tmp_path, brief,
                                                                     monkeypatch):
    root = tmp_path / "profile"
    (root / "assets").mkdir(parents=True)
    (root / "assets/logo.png").write_bytes(b"PNG-logo")
    (root / "secret.txt").write_text("not for the Studio", encoding="utf-8")

    async def detail(_db, profile_id):
        return {"id": profile_id, "profile_root": str(root)}

    monkeypatch.setattr("app.services.corp_identity_service.get_corp_identity_profile_detail", detail)
    run = await _studio_run(db, tmp_path / "run")
    await client.get(_url(run), headers=auth_headers)
    asset = f"{_url(run)}/corporate-asset"
    logo = await client.get(asset, headers=auth_headers, params={"path": "assets/logo.png"})
    assert logo.status_code == 200 and logo.content == b"PNG-logo"
    for path in ("secret.txt", "../profile/secret.txt", "icons/general/cup.svg"):
        assert (await client.get(asset, headers=auth_headers, params={"path": path})).status_code == 404


@pytest.mark.asyncio
async def test_the_agent_hears_the_company_look_and_never_the_product_owners_points(db, tmp_path, monkeypatch):
    from app.services.workflow_runs.spec_studio.hooks import submit_answer
    from app.services.workflow_runs.spec_studio.service import evaluate

    weak = {**_TEMPLATE, "theme": {**_TEMPLATE["theme"], "colors": {**_TEMPLATE["theme"]["colors"], "dk2": "#B8BEC8"}}}

    async def fake(_db, profile_id):
        return {**build_corporate_identity([weak]), "profile_id": profile_id, "profile_name": "Pale Brand"}

    monkeypatch.setattr("app.services.corp_identity.profile_edits.get_corp_identity_brief", fake)
    run = await _studio_run(db, tmp_path)
    answer = await submit_answer(db, run)
    assert answer["open_points"] == []
    assert '"Brand house"' in answer["corporate"] and "alternatives" in answer["corporate"]
    assert [p["by"] for p in evaluate(run)["open_points"]] == ["product_owner"]
