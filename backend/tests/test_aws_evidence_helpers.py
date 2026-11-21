"""Partial AWS evidence report for runs that stop before a safe model synthesis."""

from app.tools.connectors.aws_evidence_salvage import build_runtime_salvage_aws_evidence_message


def test_aws_salvage_report_uses_exact_eks_endpoint_evidence():
    message = build_runtime_salvage_aws_evidence_message(
        user_request="Validate AWS EKS and CloudWatch state in eu-central-1.",
        recent_tool_calls=[
            {
                "tool_name": "aws_read_operation",
                "status": "success",
                "parameters": {"service": "eks", "operation": "describe-cluster"},
                "result": {
                    "service": "eks",
                    "operation": "describe-cluster",
                    "result": {
                        "cluster": {
                            "name": "demo-nonprod-eks",
                            "status": "ACTIVE",
                            "version": "1.34",
                            "resourcesVpcConfig": {
                                "endpointPublicAccess": False,
                                "endpointPrivateAccess": True,
                                "vpcId": "vpc-0eccf8eace0f515cf",
                                "clusterSecurityGroupId": "sg-05990914ec7530252",
                            },
                        }
                    },
                },
            },
            {
                "tool_name": "list_aws_cloudwatch_alarms",
                "status": "success",
                "result": {
                    "count": 1,
                    "alarms": [{"AlarmName": "demo-high-cpu"}],
                },
            },
            {
                "tool_name": "aws_read_operation",
                "parameters": {"service": "rds", "operation": "describe-db-instances"},
                "result": {"error": "AWS CLI command failed"},
            },
        ],
    )

    assert "tool-iteration limit" in message
    assert "demo-nonprod-eks" in message
    assert "endpoint private only" in message
    assert "endpoint public and private" not in message
    assert "demo-high-cpu" in message
    assert "budget-blocked" in message
    assert "Residual risk:" in message


def test_aws_salvage_report_names_failed_calls_by_status():
    message = build_runtime_salvage_aws_evidence_message(
        user_request="Validate AWS CodePipeline and RDS state in eu-central-1.",
        recent_tool_calls=[
            {
                "tool_name": "list_aws_codepipelines",
                "status": "success",
                "result": {"count": 1, "pipelines": [{"name": "octryx-api"}]},
            },
            {
                "tool_name": "list_aws_codepipelines",
                "status": "error",
                "result": {"error": "AWS CLI command failed"},
            },
        ],
    )

    assert "octryx-api" in message
    assert "list_aws_codepipelines:error: 1" in message
    assert "Residual risk:" in message
