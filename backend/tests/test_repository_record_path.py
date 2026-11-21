"""A run finds its repository's coding setup also for Bitbucket Server records (the record
``bitbucket/projects/SHOP/repos/demo-shop`` must match the run's ``shop/demo-shop``, or the declared test and system
test commands are never applied)."""

from app.services.workflow_runs.platform.repo_ref import parse_repository, record_path


def test_server_record_names_match_the_runs_owner_and_repository():
    ref = parse_repository("bitbucket:SHOP/demo-shop")
    assert record_path("bitbucket/projects/SHOP/repos/demo-shop") == ref.path.lower()
    assert record_path("projects/SHOP/repos/demo-shop/") == "shop/demo-shop"
    assert record_path("acme/textkit") == "acme/textkit"
    assert record_path("demo-shop") == "demo-shop"
    assert record_path(None) == ""


def test_snapshot_record_names_carry_the_provider_first():
    assert record_path("github/acme/textkit") == "acme/textkit"
    assert record_path("bitbucket/SHOP/demo-shop") == "shop/demo-shop"
