"""Strict in-memory S3 double of the Workspace Knowledge Evidence object boundary, raising real ``botocore`` errors,
so a failure means the product is wrong rather than the double lenient."""

from __future__ import annotations

from dataclasses import dataclass, field

from botocore.exceptions import ClientError

from app.services.knowledge.objects import KnowledgeObjectStore, KnowledgeObjectStoreConfig

BUCKET = "octryx-knowledge-test"
REGION = "eu-central-1"
PREFIX = "octryx/test"


def _client_error(code: str, status: int, operation: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "server text that must never be rendered"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.closed = False

    def read(self, amount: int | None = None) -> bytes:
        return self._data if amount is None else self._data[:amount]

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeS3Client:
    objects: dict[tuple[str, str], bytes] = field(default_factory=dict)
    puts: list[dict[str, object]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    bodies: list[_Body] = field(default_factory=list)
    unavailable: bool = False
    unauthorized: bool = False
    absent_bucket: bool = False

    def _guard(self, operation: str) -> None:
        self.calls.append(operation)
        if self.absent_bucket:
            raise _client_error("NoSuchBucket", 404, operation)
        if self.unauthorized:
            raise _client_error("AccessDenied", 403, operation)
        if self.unavailable:
            raise _client_error("InternalError", 503, operation)

    def put_object(self, **kwargs: object) -> dict[str, object]:
        self._guard("PutObject")
        bucket, key = str(kwargs["Bucket"]), str(kwargs["Key"])
        if kwargs.get("IfNoneMatch") == "*" and (bucket, key) in self.objects:
            raise _client_error("PreconditionFailed", 412, "PutObject")
        body = kwargs["Body"]
        assert isinstance(body, bytes)
        self.puts.append(dict(kwargs))
        self.objects[(bucket, key)] = body
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:  # noqa: N803 - boto3 casing
        self._guard("GetObject")
        data = self.objects.get((Bucket, Key))
        if data is None:
            raise _client_error("NoSuchKey", 404, "GetObject")
        body = _Body(data)
        self.bodies.append(body)
        return {"Body": body}


def object_config(*, prefix: str | None = PREFIX) -> KnowledgeObjectStoreConfig:
    return KnowledgeObjectStoreConfig(
        scheme="http", host="127.0.0.1", port=9000, bucket=BUCKET, region=REGION, prefix=prefix
    )


def object_store(client: FakeS3Client, *, prefix: str | None = PREFIX) -> KnowledgeObjectStore:
    return KnowledgeObjectStore(object_config(prefix=prefix), client=client)
