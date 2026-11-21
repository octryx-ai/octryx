import json
import uuid

from octryx_claude.phase_brief import HEAD, JSON_LATER, MAX_CHARS, STYLE_HEAD, STYLE_LATER, phase_brief

KEY = str(uuid.UUID(int=7))  # a session key, made up
PATHS = ["preparation", "digest", "phase.code_style", "phase.code_style_brief", "phase.tools.allow"]


def _contract(digest: str, style: str = "Lines at most 100 characters.") -> dict:
    return {"run": {"id": "r-1"}, "digest": digest, "preparation": {"branch": "b"}, "detail_paths": PATHS,
            "phase": {"title": "Minimal fix", "code_style": {"x": "y" * 3000}, "code_style_brief": style,
                      "tools": {"on_device": ["Edit"], "allow": ["edit_workspace_file"]}, "findings": ["red"]}}


def test_the_phase_contract_reaches_the_model_compact_once_per_digest_and_the_style_once(state):
    first = phase_brief(state, KEY, _contract("sha256:1"))
    view = json.loads(first.removeprefix(HEAD).split(STYLE_HEAD)[0])
    assert view["phase"] == {"title": "Minimal fix", "tools": {"on_device": ["Edit"]}, "findings": ["red"]}
    assert "preparation" not in view and "detail_paths" not in view
    assert first.endswith(STYLE_HEAD + "Lines at most 100 characters.")
    assert phase_brief(state, KEY, _contract("sha256:1")) == ""  # the same contract: nothing again
    second = phase_brief(state, KEY, _contract("sha256:2"))  # the next pass: the contract again, the style not
    assert second.startswith(HEAD) and STYLE_HEAD not in second


def test_a_style_too_long_for_the_context_is_pointed_to_and_shown_when_it_fits(state):
    long = phase_brief(state, KEY, _contract("sha256:1", style="z" * MAX_CHARS))
    assert long.endswith(STYLE_LATER) and len(long) <= MAX_CHARS
    later = phase_brief(state, KEY, _contract("sha256:2", style="short style"))
    assert later.endswith(STYLE_HEAD + "short style")


def test_a_platform_without_the_compact_view_gets_no_brief(state):
    contract = _contract("sha256:1")
    del contract["detail_paths"]
    assert phase_brief(state, KEY, contract) == ""


def test_the_platform_brief_comes_first_and_a_json_that_no_longer_fits_is_left_out_whole(state):
    contract = _contract("sha256:1", style="")
    contract["phase"]["brief"] = "Phase 'Minimal fix', in short:\n- Tests: `npm test` in `e2e/node`."
    text = phase_brief(state, KEY, contract)
    assert text.startswith(contract["phase"]["brief"] + "\n\n" + HEAD)
    assert "brief" not in json.loads(text.split(HEAD)[1])["phase"]  # not twice
    contract = _contract("sha256:2", style="")
    contract["phase"]["brief"] = "Phase 'Minimal fix', in short:"
    contract["phase"]["findings"] = ["x" * MAX_CHARS]
    assert phase_brief(state, KEY, contract) == "Phase 'Minimal fix', in short:\n\n" + JSON_LATER
