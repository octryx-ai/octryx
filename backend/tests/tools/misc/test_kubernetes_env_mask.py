"""Literal env values never leave the Kubernetes tools; references stay."""

from __future__ import annotations

import json

import pytest
import yaml

from app.tools.kubernetes_env_mask import (
    KUBECTL_ENV_TEMPLATE_REFUSED,
    LAST_APPLIED,
    MASK,
    WITHHELD,
    kubectl_env_template_refusal,
    mask_describe,
    mask_kubectl_output,
)
from app.tools.kubernetes_kubectl_argv import KUBECTL_SECRET_READ_REFUSED, kubectl_subcommand_refusal
from app.tools.runtime_impl._runtime_kubectl_tool import _validate_kubectl_args

REF = {"name": "DB_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "db", "key": "password"}}}


def _deployment() -> dict:
    spec = {"containers": [{"name": "app", "env": [{"name": "API_KEY", "value": "hunter2"}, REF]}],
            "initContainers": [{"name": "init", "env": [{"name": "TOKEN", "value": "init-secret"}]}]}
    applied = {"spec": {"template": {"spec": spec}}}
    return {"kind": "Deployment", "metadata": {"name": "app", "annotations": {LAST_APPLIED: json.dumps(applied)}},
            "spec": {"template": {"spec": spec}}}


def test_json_output_masks_literal_values_in_every_container_and_the_last_applied_copy():
    out = mask_kubectl_output(["get", "deploy", "app", "-o", "json"], json.dumps({"items": [_deployment()]}))
    assert "hunter2" not in out and "init-secret" not in out
    item = json.loads(out)["items"][0]
    assert item["spec"]["template"]["spec"]["containers"][0]["env"] == [{"name": "API_KEY", "value": MASK}, REF]
    assert MASK in item["metadata"]["annotations"][LAST_APPLIED]


def test_yaml_output_is_masked_too():
    out = mask_kubectl_output(["get", "pods", "-o", "yaml"], yaml.safe_dump(_deployment()))
    assert "hunter2" not in out and "init-secret" not in out and "secretKeyRef" in out


def test_unparsable_structured_output_is_withheld():
    assert mask_kubectl_output(["get", "pods", "-o", "json"], "{not json") == WITHHELD


def test_describe_masks_the_environment_block_and_keeps_references():
    text = (
        "Containers:\n"
        "  app:\n"
        "    Image:  app:1\n"
        "    Environment:\n"
        "      API_KEY:      hunter2\n"
        "      DB_PASSWORD:  <set to the key 'password' in secret 'db'>  Optional: false\n"
        "      POD_NAME:      (v1:metadata.name)\n"
        "    Mounts:\n"
        "      /data from data (rw)\n"
    )
    out = mask_describe(text)
    assert "hunter2" not in out
    assert "<set to the key 'password' in secret 'db'>" in out and "(v1:metadata.name)" in out
    assert "/data from data (rw)" in out and f"API_KEY:      {MASK}" in out


def test_table_output_is_unchanged():
    table = "NAME   READY\napp    1/1\n"
    assert mask_kubectl_output(["get", "pods"], table) == table


@pytest.mark.parametrize("args", [
    ["get", "pods", "-o", "jsonpath={.items[*].spec.containers[*].env[*].value}"],
    ["get", "deploy", "app", "-o", "go-template={{.spec}}"],
    ["get", "all", "-o", "custom-columns=X:.spec"],
    ["get", "cronjobs.batch", "-o", "jsonpath={..value}"],
])
def test_template_formats_on_resources_with_containers_are_refused(args):
    assert kubectl_env_template_refusal(args) == KUBECTL_ENV_TEMPLATE_REFUSED
    assert kubectl_subcommand_refusal(args) == KUBECTL_ENV_TEMPLATE_REFUSED


def test_template_formats_elsewhere_still_run():
    assert kubectl_subcommand_refusal(["get", "nodes", "-o", "jsonpath={.items[*].metadata.name}"]) is None


@pytest.mark.parametrize("args, code", [
    (["get", "secrets", "-A"], KUBECTL_SECRET_READ_REFUSED),
    (["describe", "configmap", "app"], KUBECTL_SECRET_READ_REFUSED),
    (["get", "pods", "-o", "jsonpath={..value}"], KUBECTL_ENV_TEMPLATE_REFUSED),
])
def test_run_kubectl_refuses_like_the_kubernetes_tools(args, code):
    ok, message = _validate_kubectl_args(args)
    assert not ok and message == code


def test_run_kubectl_still_runs_plain_reads():
    assert _validate_kubectl_args(["get", "pods", "-o", "wide"]) == (True, "")
