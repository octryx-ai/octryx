"""The source acquisition plan pins exact source and target versions for Java and Python stacks, and the freshness policy grades sources fresh, warning, stale or unknown."""

from __future__ import annotations

from datetime import timedelta

from app.services.engineering_knowledge import evaluate_source_freshness, generate_source_acquisition_plan
from app.time_utils import utc_now


def _source_keys(plan: dict) -> set[str]:
    return {source["source_key"] for source in plan["sources"]}


def test_source_acquisition_plan_uses_exact_source_and_target_versions():
    plan = generate_source_acquisition_plan(
        stack_key="java-spring",
        source_versions={"java": "21", "spring_boot": "3.4.x"},
        target_versions={"java": "25", "spring_boot": "4.0.3"},
        source_policy={"allow_community_sources": False},
    )

    keys = _source_keys(plan)
    assert plan["source_versions"] == {"java": "21", "spring_boot": "3.4.x"}
    assert plan["target_versions"] == {"java": "25", "spring_boot": "4.0.3"}
    assert "oracle-java-25-api" in keys
    assert "oracle-java-25-release-notes" in keys
    assert "spring-boot-4-0-3-reference" in keys
    assert "spring-boot-4-0-3-dependencies" in keys
    assert "openrewrite-spring-boot-4-0-3-recipes" in keys
    assert all(source["metadata"]["target_version"] in {"25", "4.0.3"} for source in plan["sources"])


def test_source_acquisition_plan_supports_python_stack_sources():
    plan = generate_source_acquisition_plan(
        stack_key="python",
        source_versions={"python": "3.11"},
        target_versions={"python": "3.12"},
        source_policy={"allow_community_sources": False},
    )

    keys = _source_keys(plan)
    assert plan["source_versions"] == {"python": "3.11"}
    assert plan["target_versions"] == {"python": "3.12"}
    assert {
        "python-3-12-docs",
        "python-3-12-whats-new",
        "python-packaging-user-guide",
        "ruff-documentation",
    } <= keys
    assert any(source["trust_tier"] == "vendor" for source in plan["sources"])


def test_source_freshness_policy_has_fresh_warning_stale_and_unknown_states():
    now = utc_now()
    policy = {"ttl_days": 30, "warning_days": 21}

    assert evaluate_source_freshness(fetched_at=None, freshness_policy=policy, now=now) == "unknown"
    assert evaluate_source_freshness(fetched_at=now - timedelta(days=1), freshness_policy=policy, now=now) == "fresh"
    assert evaluate_source_freshness(fetched_at=now - timedelta(days=22), freshness_policy=policy, now=now) == "warning"
    assert evaluate_source_freshness(fetched_at=now - timedelta(days=31), freshness_policy=policy, now=now) == "stale"
