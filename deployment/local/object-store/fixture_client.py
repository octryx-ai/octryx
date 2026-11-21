"""Fixture-only S3 client: everything the product boundary deliberately cannot do.

The Knowledge object boundary owns exactly ``PutObject`` and ``GetObject``, so a
live smoke still needs a second, clearly separated actor to create the bucket and
to plant an object whose stored bytes do not match the digest they are addressed
by. That actor lives here, uses the fixture administrator identity, and runs on
its own ``boto3`` session so the product wire observer never records it.

Nothing here is product code and nothing here may be reused by product code.
Credentials are held only for the lifetime of the client and are never logged.
"""

from __future__ import annotations

import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

READY_ATTEMPTS = 40
READY_DELAY_SECONDS = 1.0
# Codes that mean "the bucket is there and it is ours", i.e. readiness reached.
_BUCKET_PRESENT = frozenset({"BucketAlreadyOwnedByYou", "BucketAlreadyExists"})
# A rejected credential or a refused grant is a configuration fault, never a
# transient start-up state, so readiness must fail immediately instead of looping.
_FATAL = frozenset({"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"})


class FixtureError(Exception):
    """A fixed, secret-free fixture failure."""


def _error_code(error: ClientError) -> str:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return ""
    details = response.get("Error")
    code = details.get("Code") if isinstance(details, dict) else None
    return code if type(code) is str and code.isalnum() else ""


class FixtureAdmin:
    """Administrative S3 access used only to set up and corrupt fixture state."""

    def __init__(self, endpoint_url: str, region: str, access_key_id: str, secret_access_key: str) -> None:
        # A dedicated session, not the boto3 default one: the default session is
        # where the product client is observed, and these calls are not product calls.
        session = boto3.session.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            aws_session_token=None,
            region_name=region,
        )
        self._client = session.client(
            "s3",
            endpoint_url=endpoint_url,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=5,
                read_timeout=5,
                retries={"max_attempts": 1, "mode": "standard"},
            ),
        )

    def wait_until_bucket_exists(self, bucket: str) -> int:
        """Create the fixture bucket, retrying until the runtime serves writes.

        The Compose health check only proves the S3 listener answers; master,
        volume and filer come up behind it. A successful ``CreateBucket`` is the
        first point at which the runtime is genuinely usable, so it is the
        readiness gate. Returns the number of attempts it took.
        """
        last = ""
        for attempt in range(1, READY_ATTEMPTS + 1):
            try:
                self._client.create_bucket(Bucket=bucket)
                return attempt
            except ClientError as error:
                code = _error_code(error)
                if code in _BUCKET_PRESENT:
                    return attempt
                if code in _FATAL:
                    raise FixtureError(f"readiness: the fixture identity was refused ({code})") from None
                last = code or "no-code"
            except BotoCoreError:
                last = "transport"
            time.sleep(READY_DELAY_SECONDS)
        raise FixtureError(f"readiness: the runtime did not accept a bucket within the bound (last: {last})")

    def checksum_rejection_code(self, bucket: str, key: str, body: bytes, checksum: str) -> str:
        """Return the code the server refuses a wrong ``ChecksumSHA256`` with.

        The product never sends a checksum that disagrees with its body, so this
        server capability cannot be proven through product code. It has to be
        proven, because the boundary relies on the server validating the digest it
        is addressed by. Returns "" when the write was accepted, which is a failure.
        """
        try:
            self._client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentLength=len(body),
                ChecksumSHA256=checksum,
            )
        except ClientError as error:
            return _error_code(error) or "no-code"
        except BotoCoreError:
            return "transport"
        return ""

    def get_rejection_code(self, bucket: str, key: str) -> str:
        """Return the code a ``GetObject`` is refused with, or "" when it succeeded.

        Used with the reconciliation credentials, which hold no ``Read`` grant. The
        product's maintenance capability has no read operation at all, so the *identity's*
        inability to read Workspace bytes can only be shown from outside product code.
        """
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
        except ClientError as error:
            return _error_code(error) or "no-code"
        except BotoCoreError:
            return "transport"
        body = response.get("Body")
        if body is not None:
            body.close()
        return ""

    def plant_object(self, bucket: str, key: str, body: bytes) -> None:
        """Write ``body`` at ``key`` with no checksum and no precondition.

        Used to create the one state the product boundary cannot create itself:
        stored bytes that disagree with the content address they sit at.
        """
        try:
            self._client.put_object(Bucket=bucket, Key=key, Body=body, ContentLength=len(body))
        except (ClientError, BotoCoreError) as error:
            code = _error_code(error) if isinstance(error, ClientError) else "transport"
            raise FixtureError(f"fixture write: refused ({code or 'no-code'})") from None
