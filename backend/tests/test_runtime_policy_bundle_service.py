import uuid

import pytest

import app.services.runtime_policy_bundle as runtime_policy_bundle_package
import app.services.runtime_policy_bundle as runtime_policy_bundle_root
from app.models import Project
from app.services.project import get_project_config
from app.services.runtime_policy_bundle import (
    apply_runtime_policy_bundle,
    normalize_runtime_policy_config,
)
from app.services.runtime_policy_bundle import service as runtime_policy_bundle_service_package


def test_runtime_policy_bundle_service_root_shim_matches_package_surface() -> None:
    exported_names = [
        "apply_runtime_policy_bundle",
        "normalize_runtime_policy_bundle",
        "normalize_runtime_policy_config",
        "resolve_runtime_policy_bundle",
    ]

    assert runtime_policy_bundle_root.__all__ == exported_names
    assert runtime_policy_bundle_package.__all__ == exported_names

    for name in exported_names:
        assert getattr(runtime_policy_bundle_root, name) is getattr(runtime_policy_bundle_package, name)
        assert getattr(runtime_policy_bundle_root, name) is getattr(runtime_policy_bundle_service_package, name)


def test_apply_runtime_policy_bundle_merges_default_and_environment():
    config = apply_runtime_policy_bundle(
        {
            "runtime_policy": {
                "active_environment": "production",
                "default_bundle": {
                    "security_analyzer_chain": ["exec_policy", "llm_risk"],
                    "llm_security_analyzer_review_threshold": 45,
                },
                "environment_bundles": {
                    "production": {
                        "execution_runtime_provider": "docker",
                        "execution_runtime_sandbox_mode": "hard",
                        "execution_runtime_allow_host_fallback": True,
                        "execution_runtime_docker_network_mode": "host",
                        "llm_security_analyzer_deny_threshold": 92,
                    }
                },
            }
        }
    )

    assert config["security_analyzer_chain"] == ["exec_policy", "llm_risk"]
    assert config["llm_security_analyzer_review_threshold"] == 45
    assert config["execution_runtime_provider"] == "docker"
    assert config["execution_runtime_sandbox_mode"] == "hard"
    assert config["execution_runtime_allow_host_fallback"] is False
    assert config["execution_runtime_docker_network_mode"] == "bridge"
    assert config["llm_security_analyzer_deny_threshold"] == 92
    assert config["effective_runtime_policy"]["execution_runtime_provider"] == "docker"


def test_normalize_runtime_policy_config_clamps_threshold_order():
    normalized = normalize_runtime_policy_config(
        {
            "active_environment": "prod",
            "environment_bundles": {
                "prod": {
                    "llm_security_analyzer_review_threshold": 70,
                    "llm_security_analyzer_deny_threshold": 40,
                }
            },
        }
    )

    assert normalized["environment_bundles"]["prod"]["llm_security_analyzer_review_threshold"] == 70
    assert normalized["environment_bundles"]["prod"]["llm_security_analyzer_deny_threshold"] == 70


@pytest.mark.asyncio
async def test_get_project_config_applies_runtime_policy_bundle(db):
    project = Project(
        id=str(uuid.uuid4()),
        name="runtime-policy-project",
        config={
            "runtime_policy": {
                "active_environment": "production",
                "default_bundle": {"security_review_model": "security-model-v1"},
                "environment_bundles": {
                    "production": {
                        "execution_runtime_provider": "docker",
                        "llm_security_analyzer_review_threshold": 55,
                    }
                },
            }
        },
        is_active=True,
    )
    db.add(project)
    await db.commit()

    config = await get_project_config(project.id, db)

    assert config["security_review_model"] == "security-model-v1"
    assert config["execution_runtime_provider"] == "docker"
    assert config["llm_security_analyzer_review_threshold"] == 55
    assert config["effective_runtime_policy"]["execution_runtime_provider"] == "docker"
