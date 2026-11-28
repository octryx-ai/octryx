"""The context checkpoint package exports its service surface; the checkpoint name contract."""

from app.services import context_checkpoint as context_checkpoint_service
from app.services.context_checkpoint import service as context_checkpoint_package_service


def test_context_checkpoint_package_exports_its_service_surface() -> None:
    exported_names = (
        "ACTIVE_STATUS",
        "ALLOWED_RELEASE_ACTIONS",
        "RELEASED_STATUS",
        "ROLLED_BACK_STATUS",
        "_clean_checkpoint_name",
        "_snapshot_copy",
        "create_context_checkpoint",
        "get_active_context_checkpoint",
        "list_context_checkpoints",
        "release_context_checkpoint",
        "render_context_checkpoint_for_prompt",
    )

    for name in exported_names:
        assert getattr(context_checkpoint_service, name) is getattr(context_checkpoint_package_service, name)


def test_clean_checkpoint_name_contract_is_stable() -> None:
    assert context_checkpoint_service._clean_checkpoint_name(None) == "checkpoint"
    assert context_checkpoint_service._clean_checkpoint_name("  release branch  ") == "release branch"
    assert len(context_checkpoint_service._clean_checkpoint_name("x" * 300)) == 200
