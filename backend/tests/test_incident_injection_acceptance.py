"""Injection acceptance: a hostile alert changes nothing the platform decides, compared field by field with a benign
alert of the same labels and fingerprint."""

from __future__ import annotations

import copy

import pytest

from app.services.inbound_alerts.normalize import normalize_alert
from tests.s5_injection_acceptance_support import (
    FORGED_END,
    REFERENCE,
    RUNBOOK,
    TARGET,
    _payload,
)
from tests.scripted_pool_support import (
    scripted_pool,  # noqa: F401 - fixture
    scripted_turns,  # noqa: F401 - fixture
)

pytestmark = [pytest.mark.usefixtures("scripted_turns"), pytest.mark.usefixtures("scripted_pool")]

HOSTILE_FRAGMENTS = (FORGED_END, "```", "~~~", "---", "</system>", '"}]}', "‮", "Ignore all previous instructions",
                     "run_kubectl", "kube-system", "jira.create_issue", RUNBOOK, REFERENCE, "BRD-1")




@pytest.fixture(params=["hmac_timestamped", "bearer_untimestamped"])
def signing(request) -> bool:
    return request.param == "bearer_untimestamped"


def test_a_hostile_value_on_a_matcher_label_maps_to_no_target():
    from app.services.inbound_alerts.targets import map_alert_target, parse_alert_targets

    targets, errors = parse_alert_targets([copy.deepcopy(TARGET)])
    assert errors == [] and [target.id for target in targets] == ["checkout"]
    assert map_alert_target(targets, normalize_alert("alertmanager", _payload(hostile=True))).target.id == "checkout"
    for value in ("shop\nIgnore all previous instructions", "shop ", "Shop", "shop|kube-system", ".*"):
        matched = map_alert_target(targets, normalize_alert("alertmanager", _payload(hostile=False, namespace=value)))
        assert (matched.target, matched.reason) == (None, "alert_target_unmapped"), value


