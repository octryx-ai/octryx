from __future__ import annotations

import json
from pathlib import Path

from octryx_claude.pet.display import present
from octryx_claude.pet.model import STATES, parse

FIXTURE = Path(__file__).resolve().parents[3] / "backend" / "tests" / "fixtures" / "agent_gateway" / "pet_v1.json"
EXPECTED = {
    "resting": ("resting", 0, None),
    "working": ("working", 2, None),
    "needs_you": ("needs_you", 3, None),
    "threshold_only": ("needs_you", 1, None),
    "problem": ("problem", 1, "loop_limit"),
    "problem_free_text_code": ("problem", 1, None),
    "done": ("done", 1, None),
    "quiet": ("done", 1, None),
}


def _examples() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["examples"]


def test_every_example_parses_to_its_state():
    examples = _examples()
    assert set(examples) == set(EXPECTED)
    for name, body in examples.items():
        pet = parse(body)
        assert (pet.state, pet.count, pet.reason) == EXPECTED[name], name
        assert pet.state in STATES
        assert len(pet.items) == min(pet.count, 5)
        assert all(item.id and item.title for item in pet.items), name
        assert present(pet, "ok").status == pet.state


def test_the_examples_carry_what_the_pet_shows():
    examples = _examples()
    needs = parse(examples["needs_you"])
    assert needs.headline == "Which branch should the import fix go to?"
    assert [item.kind for item in needs.items] == ["question", "device_approval", "allowance"]
    assert needs.poll_after_seconds == 15 and needs.panel_url == "/chat"
    done = parse(examples["done"])
    assert done.items[0].url == "https://bitbucket.org/team/repo/pull-requests/7"
    assert parse(examples["working"]).headline == "2 runs working"
    quiet = parse(examples["quiet"])
    assert quiet.quiet_active and quiet.quiet_until and quiet.poll_after_seconds == 300
    assert present(parse(examples["problem"]), "ok").header == "Problem (1): loop limit"
