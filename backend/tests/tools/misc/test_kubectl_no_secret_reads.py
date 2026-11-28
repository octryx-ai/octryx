"""The platform's Kubernetes tools never show Secret contents or ConfigMap data; they run with the API's
credentials, so the refusal holds with or without an alert scope."""

from __future__ import annotations

import pytest

from app.tools.kubernetes_kubectl_argv import KUBECTL_SECRET_READ_REFUSED, kubectl_subcommand_refusal


@pytest.mark.parametrize("args", [
    ["get", "secrets"],
    ["get", "secret", "db", "-o", "yaml"],
    ["get", "Secret.v1", "-A"],
    ["get", "pods,secrets"],
    ["get", "secret/db", "-o", "jsonpath={.data}"],
    ["describe", "secrets", "-n", "x"],
    ["describe", "configmap", "app"],
    ["get", "cm", "app", "-o", "yaml"],
    ["get", "configmaps", "-o", "jsonpath={.items[*].data}"],
    ["get", "configmap/app", "-o", "json"],
])
def test_secret_contents_and_configmap_data_are_refused(args):
    assert kubectl_subcommand_refusal(args) == KUBECTL_SECRET_READ_REFUSED


@pytest.mark.parametrize("args", [
    ["get", "pods"],
    ["get", "configmaps"],
    ["get", "cm", "-o", "name"],
    ["describe", "pod", "api-1"],
    ["get", "events", "-n", "x"],
])
def test_other_reads_still_run(args):
    assert kubectl_subcommand_refusal(args) is None
