"""Tool definitions for individual AWS services (CloudWatch, EC2, RDS, Lambda, CloudTrail, cost, CodePipeline, WAF)."""

from __future__ import annotations

AWS_SERVICE_DEFINITIONS: dict[str, dict] = {
    "list_aws_cloudwatch_alarms": {
        "type": "function",
        "function": {
            "name": "list_aws_cloudwatch_alarms",
            "description": "List CloudWatch alarms in the configured AWS account and region",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "list_aws_ec2_instances": {
        "type": "function",
        "function": {
            "name": "list_aws_ec2_instances",
            "description": "List EC2 instances",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
    "start_aws_ec2_instances": {
        "type": "function",
        "function": {
            "name": "start_aws_ec2_instances",
            "description": "Start EC2 instances with approval",
            "parameters": {
                "type": "object",
                "properties": {"instance_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["instance_ids"],
            },
        },
    },
    "stop_aws_ec2_instances": {
        "type": "function",
        "function": {
            "name": "stop_aws_ec2_instances",
            "description": "Stop EC2 instances with approval",
            "parameters": {
                "type": "object",
                "properties": {"instance_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["instance_ids"],
            },
        },
    },
    "get_aws_ec2_logs": {
        "type": "function",
        "function": {
            "name": "get_aws_ec2_logs",
            "description": "Get CloudWatch log events for EC2 workloads",
            "parameters": {
                "type": "object",
                "properties": {
                    "log_group_name": {"type": "string"},
                    "log_stream_names": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
                "required": ["log_group_name"],
            },
        },
    },
    "list_aws_rds_instances": {
        "type": "function",
        "function": {
            "name": "list_aws_rds_instances",
            "description": "List RDS instances",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
    "get_aws_rds_metrics": {
        "type": "function",
        "function": {
            "name": "get_aws_rds_metrics",
            "description": "Get CloudWatch metrics for an RDS instance",
            "parameters": {
                "type": "object",
                "properties": {
                    "db_instance_identifier": {"type": "string"},
                    "metric_name": {"type": "string"},
                    "hours": {"type": "integer"},
                    "period_seconds": {"type": "integer"},
                    "statistic": {"type": "string"},
                },
                "required": ["db_instance_identifier"],
            },
        },
    },
    "get_aws_rds_slow_queries": {
        "type": "function",
        "function": {
            "name": "get_aws_rds_slow_queries",
            "description": "Read RDS slow query logs",
            "parameters": {
                "type": "object",
                "properties": {
                    "db_instance_identifier": {"type": "string"},
                    "log_file_name": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["db_instance_identifier", "log_file_name"],
            },
        },
    },
    "list_aws_lambda_functions": {
        "type": "function",
        "function": {
            "name": "list_aws_lambda_functions",
            "description": "List Lambda functions",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
    "get_aws_lambda_logs": {
        "type": "function",
        "function": {
            "name": "get_aws_lambda_logs",
            "description": "Get CloudWatch log events for a Lambda function",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {"type": "string"},
                    "log_group_name": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["function_name"],
            },
        },
    },
    "invoke_aws_lambda": {
        "type": "function",
        "function": {
            "name": "invoke_aws_lambda",
            "description": "Invoke a Lambda function with approval",
            "parameters": {
                "type": "object",
                "properties": {"function_name": {"type": "string"}, "payload": {}},
                "required": ["function_name"],
            },
        },
    },
    "search_aws_cloudtrail_events": {
        "type": "function",
        "function": {
            "name": "search_aws_cloudtrail_events",
            "description": "Search CloudTrail events",
            "parameters": {
                "type": "object",
                "properties": {
                    "lookup_attribute_key": {"type": "string"},
                    "lookup_attribute_value": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_aws_cost_by_service": {
        "type": "function",
        "function": {
            "name": "get_aws_cost_by_service",
            "description": "Get AWS cost grouped by service",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "granularity": {"type": "string"},
                },
            },
        },
    },
    "list_aws_codepipelines": {
        "type": "function",
        "function": {
            "name": "list_aws_codepipelines",
            "description": "List CodePipeline pipelines in the configured AWS account/region",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
    "get_aws_codepipeline_state": {
        "type": "function",
        "function": {
            "name": "get_aws_codepipeline_state",
            "description": "Get the current execution state of a CodePipeline pipeline including stage and action statuses",
            "parameters": {
                "type": "object",
                "properties": {"pipeline_name": {"type": "string"}},
                "required": ["pipeline_name"],
            },
        },
    },
    "list_aws_codepipeline_executions": {
        "type": "function",
        "function": {
            "name": "list_aws_codepipeline_executions",
            "description": "List recent executions of a CodePipeline pipeline",
            "parameters": {
                "type": "object",
                "properties": {
                    "pipeline_name": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["pipeline_name"],
            },
        },
    },
    "start_aws_codepipeline_execution": {
        "type": "function",
        "function": {
            "name": "start_aws_codepipeline_execution",
            "description": "Start a new execution of a CodePipeline pipeline (requires approval)",
            "parameters": {
                "type": "object",
                "properties": {"pipeline_name": {"type": "string"}},
                "required": ["pipeline_name"],
            },
        },
    },
    "list_aws_waf_web_acls": {
        "type": "function",
        "function": {
            "name": "list_aws_waf_web_acls",
            "description": "List WAFv2 Web ACLs in the configured AWS account/region",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "description": "REGIONAL or CLOUDFRONT"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    "get_aws_waf_web_acl": {
        "type": "function",
        "function": {
            "name": "get_aws_waf_web_acl",
            "description": "Get details of a WAFv2 Web ACL including rules",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "id": {"type": "string"},
                    "scope": {"type": "string", "description": "REGIONAL or CLOUDFRONT"},
                },
                "required": ["name", "id"],
            },
        },
    },
}
