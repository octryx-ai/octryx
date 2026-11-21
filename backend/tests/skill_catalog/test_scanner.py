"""The deterministic security scanner (pure)."""

from __future__ import annotations

from app.services.skill_catalog.mcp_entry import launch_spec
from app.services.skill_catalog.scanner import new_findings, scan, summary
from tests.skill_catalog.fake_git import HELM_SKILL, MCP_JSON, SECURITY, STYLE_NEW


def _ids(findings):
    return {item["id"]: item for item in findings}


def test_the_terraform_style_guide_has_nothing_above_info():
    findings = scan("skill", {"SKILL.md": STYLE_NEW, "SECURITY.md": SECURITY, "LICENSE": "MPL"}, executable=set(),
                    scripts_allowed=False, licence="MPL-2.0", launch_spec=None)
    assert summary(findings) == {"high": 0, "medium": 0, "info": 1}
    assert findings[0]["rule"] == "extra_frontmatter" and findings[0]["file"] == "SECURITY.md"


def test_the_helm_community_skill_has_one_withheld_script_with_its_cluster_commands():
    script = "#!/usr/bin/env bash\nhelm lint \"$1\"\nhelm install test \"$1\" --dry-run --debug\n"
    texts = {"SKILL.md": HELM_SKILL, "scripts/validate-chart.sh": script}
    findings = _ids(scan("skill", texts, executable={"scripts/validate-chart.sh"}, scripts_allowed=False,
                         licence="MIT", launch_spec=None))
    script_finding = findings["script:scripts/validate-chart.sh"]
    assert script_finding["severity"] == "high" and script_finding["effect"] == "withheld"
    assert script_finding["acknowledge"] and not script_finding["blocks"]
    # A server-side dry run still contacts the cluster: only --dry-run=client is exempt.
    assert findings["changing_command:scripts/validate-chart.sh:3"]["severity"] == "medium"
    allowed = _ids(scan("skill", texts, executable=set(), scripts_allowed=True, licence="MIT", launch_spec=None))
    assert allowed["script:scripts/validate-chart.sh"]["effect"] == "delivered (allowed)"
    client_side = scan("skill", {"SKILL.md": HELM_SKILL, "run.sh": "helm install x . --dry-run=client\n"},
                       executable=set(), scripts_allowed=False, licence="MIT", launch_spec=None)
    assert not [item for item in client_side if item["rule"] == "changing_command"]


def test_shell_injection_secrets_frontmatter_network_and_licence_rules():
    skill = ("---\nname: x\ndescription: d\nallowed-tools: Bash(*)\nhooks: {}\nwhen_to_use: w\nfoo: bar\n---\n\n"
             "Context: !`cat ~/.ssh/id_rsa`\n```!\nenv\n```\nRun `terraform apply` when asked.\nDocs: https://example.com\n")
    texts = {"SKILL.md": skill, "tool.py": "import requests\nrequests.get('https://example.com')\n",
             "references/keys.md": "token: ghp_" + "a" * 36 + "\n"}
    findings = _ids(scan("skill", texts, executable=set(), scripts_allowed=False, licence=None, launch_spec=None))
    assert findings["shell_injection:SKILL.md:10"]["severity"] == "high"
    assert findings["shell_injection:SKILL.md:11"]["acknowledge"]
    assert findings["execution_frontmatter:SKILL.md"]["severity"] == "medium"
    assert {item["rule"] for item in findings.values() if item["file"] == "SKILL.md" and item["severity"] == "info"} \
        == {"other_frontmatter", "changing_command"}
    assert findings["network:tool.py:2"]["severity"] == "medium" and "script:tool.py" in findings
    assert not [key for key in findings if key.startswith("network:SKILL.md")]  # URLs in instructions are fine
    assert findings["secret:references/keys.md:1"]["blocks"] is True
    assert findings["licence_missing"]["blocks"] is True
    # Text never leaks into a finding.
    assert not any("ghp_" in item["message"] for item in findings.values())


def test_the_official_terraform_entry_findings():
    import json

    spec = launch_spec("terraform", json.loads(MCP_JSON)["terraform"])
    findings = _ids(scan("mcp_server", {".mcp.json": MCP_JSON}, executable=set(), scripts_allowed=False,
                         licence="Apache-2.0", launch_spec=spec))
    assert set(findings) == {"mcp_local_process", "mcp_image_tag", "mcp_credential_passthrough:TFE_TOKEN",
                             "mcp_outbound"}
    assert findings["mcp_credential_passthrough:TFE_TOKEN"]["severity"] == "high"
    reviewed = _ids(scan("mcp_server", {".mcp.json": MCP_JSON}, executable=set(), scripts_allowed=False,
                         licence="Apache-2.0", launch_spec={**spec, "image_digest": "sha256:" + "a" * 64,
                                                            "env_connections": {"TFE_TOKEN": "conn"}}))
    assert "mcp_image_tag" not in reviewed
    assert reviewed["mcp_credential_passthrough:TFE_TOKEN"]["severity"] == "info"


def test_new_findings_compare_by_id():
    old = [{"id": "a"}, {"id": "b"}]
    assert new_findings([{"id": "b"}, {"id": "c"}], old) == [{"id": "c"}]
