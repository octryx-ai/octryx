"""Strict test doubles for the operator-owned object reconciliation slice: the maintenance client has only
``list_objects_v2`` and records every prefix it was asked for."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from botocore.exceptions import ClientError

from app.services.knowledge.objects import KnowledgeObjectMaintenance
from app.time_utils import utc_now
from tests.support.knowledge_evidence_s3_support import PREFIX, FakeS3Client, object_config


def _client_error(code: str, status: int, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "server text that must never be rendered"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


@dataclass
class FakeMaintenanceClient:
    source: FakeS3Client = field(default_factory=FakeS3Client)
    modified: dict[str, datetime] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    prefixes: list[str] = field(default_factory=list)
    unavailable: bool = False
    unauthorized: bool = False
    absent_bucket: bool = False

    def plant(self, bucket: str, key: str, data: bytes, *, age_hours: int = 0) -> None:
        self.source.objects[(bucket, key)] = data
        self.modified[key] = utc_now() - timedelta(hours=age_hours)

    def age(self, key: str, *, hours: int) -> None:
        self.modified[key] = utc_now() - timedelta(hours=hours)

    def _guard(self, operation: str) -> None:
        self.calls.append(operation)
        if self.absent_bucket:
            raise _client_error("NoSuchBucket", 404, operation)
        if self.unauthorized:
            raise _client_error("AccessDenied", 403, operation)
        if self.unavailable:
            raise _client_error("InternalError", 503, operation)

    # boto3 casing, like the evidence store double's ``get_object``.
    def list_objects_v2(self, *, Bucket: str, Prefix: str, MaxKeys: int, StartAfter: str | None = None) -> dict:  # noqa: N803,E501
        self._guard("ListObjectsV2")
        self.prefixes.append(Prefix)
        keys = sorted(key for bucket, key in self.source.objects if bucket == Bucket and key.startswith(Prefix))
        if StartAfter is not None:
            keys = [key for key in keys if key > StartAfter]
        page = keys[:MaxKeys]
        return {
            "Contents": [
                {
                    "Key": key,
                    "Size": len(self.source.objects[(Bucket, key)]),
                    "LastModified": self.modified.get(key, utc_now()),
                }
                for key in page
            ],
            "IsTruncated": len(keys) > len(page),
            "KeyCount": len(page),
        }


def maintenance(client: FakeMaintenanceClient, *, prefix: str | None = PREFIX) -> KnowledgeObjectMaintenance:
    return KnowledgeObjectMaintenance(object_config(prefix=prefix), client=client)
