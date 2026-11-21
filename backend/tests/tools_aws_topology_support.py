"""Recorded AWS CLI answers behind the AWS topology snapshot tool test (one account, one VPC)."""

from __future__ import annotations

import copy
from typing import Any

# Answers for one (service, operation) call.
TOPOLOGY_OPERATION_RESPONSES: dict[tuple[str, str], dict[str, Any]] = {
    ("ec2", "describe-vpcs"): {"Vpcs": [{"VpcId": "vpc-1", "CidrBlock": "10.0.0.0/16", "State": "available"}]},
    ("ec2", "describe-subnets"): {
        "Subnets": [
            {
                "SubnetId": "subnet-1",
                "VpcId": "vpc-1",
                "AvailabilityZone": "eu-central-1a",
                "CidrBlock": "10.0.1.0/24",
            }
        ]
    },
    ("ec2", "describe-security-groups"): {
        "SecurityGroups": [
            {
                "GroupId": "sg-1",
                "VpcId": "vpc-1",
                "GroupName": "app",
                "IpPermissions": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 443,
                        "ToPort": 443,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    },
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 5432,
                        "ToPort": 5432,
                        "UserIdGroupPairs": [{"GroupId": "sg-2", "GroupName": "database-clients"}],
                    },
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 3306,
                        "ToPort": 3306,
                        "UserIdGroupPairs": [{"GroupId": "sg-2", "GroupName": "database-clients"}],
                    },
                ],
                "IpPermissionsEgress": [
                    {
                        "IpProtocol": "tcp",
                        "FromPort": 443,
                        "ToPort": 443,
                        "IpRanges": [{"CidrIp": "10.0.2.0/24"}],
                    }
                ],
            },
            {
                "GroupId": "sg-2",
                "VpcId": "vpc-1",
                "GroupName": "database-clients",
                "IpPermissions": [],
                "IpPermissionsEgress": [],
            },
        ]
    },
    ("ec2", "describe-internet-gateways"): {
        "InternetGateways": [
            {
                "InternetGatewayId": "igw-1",
                "Attachments": [{"VpcId": "vpc-1", "State": "available"}],
            }
        ]
    },
    ("ec2", "describe-nat-gateways"): {"NatGateways": []},
    ("ec2", "describe-route-tables"): {
        "RouteTables": [
            {
                "RouteTableId": "rtb-1",
                "VpcId": "vpc-1",
                "Associations": [{"SubnetId": "subnet-1"}],
                "Routes": [{"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-1"}],
            }
        ]
    },
    ("elbv2", "describe-load-balancers"): {
        "LoadBalancers": [
            {
                "LoadBalancerArn": "arn:aws:elasticloadbalancing:eu-central-1:123456789012:loadbalancer/app/app/1",
                "LoadBalancerName": "app-lb",
                "VpcId": "vpc-1",
                "Scheme": "internet-facing",
                "Type": "application",
                "AvailabilityZones": [{"SubnetId": "subnet-1"}],
                "SecurityGroups": ["sg-1"],
            }
        ]
    },
    ("elbv2", "describe-target-groups"): {
        "TargetGroups": [
            {
                "TargetGroupArn": "arn:aws:elasticloadbalancing:eu-central-1:123456789012:targetgroup/app/1",
                "TargetGroupName": "app-tg",
                "VpcId": "vpc-1",
                "LoadBalancerArns": ["arn:aws:elasticloadbalancing:eu-central-1:123456789012:loadbalancer/app/app/1"],
            }
        ]
    },
    ("eks", "list-clusters"): {"clusters": ["nonprod"]},
    ("eks", "describe-cluster"): {
        "cluster": {
            "name": "nonprod",
            "arn": "arn:aws:eks:eu-central-1:123456789012:cluster/nonprod",
            "status": "ACTIVE",
            "version": "1.31",
            "resourcesVpcConfig": {
                "vpcId": "vpc-1",
                "subnetIds": ["subnet-1"],
                "securityGroupIds": ["sg-1"],
            },
        }
    },
    ("eks", "list-nodegroups"): {"nodegroups": ["app-ng"]},
    ("eks", "describe-nodegroup"): {
        "nodegroup": {
            "clusterName": "nonprod",
            "nodegroupName": "app-ng",
            "nodegroupArn": "arn:aws:eks:eu-central-1:123456789012:nodegroup/nonprod/app-ng/1",
            "status": "ACTIVE",
            "capacityType": "ON_DEMAND",
            "instanceTypes": ["m7i.large"],
            "subnets": ["subnet-1"],
            "scalingConfig": {"minSize": 1, "maxSize": 3, "desiredSize": 2},
            "resources": {"autoScalingGroups": [{"name": "eks-app-ng-asg"}]},
        }
    },
    ("dynamodb", "list-tables"): {"TableNames": ["audit-events"]},
    ("dynamodb", "describe-table"): {
        "Table": {
            "TableName": "audit-events",
            "TableArn": "arn:aws:dynamodb:eu-central-1:123456789012:table/audit-events",
            "TableStatus": "ACTIVE",
            "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
            "ItemCount": 42,
            "StreamSpecification": {"StreamEnabled": True, "StreamViewType": "NEW_AND_OLD_IMAGES"},
        }
    },
    ("wafv2", "list-resources-for-web-acl"): {
        "ResourceArns": ["arn:aws:elasticloadbalancing:eu-central-1:123456789012:loadbalancer/app/app/1"]
    },
}
# Answers for every other operation of a service.
TOPOLOGY_SERVICE_RESPONSES: dict[str, dict[str, Any]] = {
    "sts": {
        "Account": "123456789012",
        "Arn": "arn:aws:sts::123456789012:assumed-role/octryx-irsa-role/session",
        "UserId": "role-id",
    },
    "rds": {
        "DBInstances": [
            {
                "DBInstanceIdentifier": "app-db",
                "DBInstanceArn": "arn:aws:rds:eu-central-1:123456789012:db:app-db",
                "Engine": "postgres",
                "DBSubnetGroup": {
                    "VpcId": "vpc-1",
                    "Subnets": [{"SubnetIdentifier": "subnet-1"}],
                },
                "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-1"}],
            }
        ]
    },
    "codepipeline": {"pipelines": [{"name": "base_apply", "version": 1}]},
    "wafv2": {
        "WebACLs": [
            {
                "Name": "customer-access",
                "Id": "waf-1",
                "ARN": "arn:aws:wafv2:eu-central-1:123456789012:regional/webacl/customer-access/waf-1",
            }
        ]
    },
}


async def fake_topology_aws_json(context, service, command):
    """A fresh copy of the recorded answer, as each real CLI call returns."""
    operation = command[0]
    if (service, operation) in TOPOLOGY_OPERATION_RESPONSES:
        return copy.deepcopy(TOPOLOGY_OPERATION_RESPONSES[(service, operation)])
    if service in TOPOLOGY_SERVICE_RESPONSES:
        return copy.deepcopy(TOPOLOGY_SERVICE_RESPONSES[service])
    raise AssertionError(f"unexpected AWS call {service} {command}")
