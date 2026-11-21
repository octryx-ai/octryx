"""Shared helpers for the test_office_documents_service_* modules."""

import pytest

from tests.office_template_support import isolate_corp_identity_root


@pytest.fixture(autouse=True)
def _isolated_corp_identity_store(monkeypatch, tmp_path):
    isolate_corp_identity_root(monkeypatch, tmp_path)
