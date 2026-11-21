"""The fixed contract of the local object-store fixture and its credential intake.

Owns everything the smoke shares with ``fixture.sh``: the identity and bucket
names, the least-privilege grants each identity must carry, the acceptance
Workspaces and payloads, and the explicit configuration mapping the product
validates for itself. Reading the generated identity file and shutting every
other source of the AWS credential chain live here too, because both are about
what the fixture is allowed to hand to the product.

No product assertion belongs in this module, and nothing here is product code.
Secret keys are returned to the caller and never printed.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path

HOST = "127.0.0.1"
DEFAULT_PORT = 8333
REGION = "us-east-1"
PREFIX = "octryx-local-smoke"

# Must stay identical to fixture.sh; the identity file is cross-checked below.
ADMIN_IDENTITY = "octryx-local-smoke-fixture-admin"
CLIENT_IDENTITY = "octryx-local-smoke-knowledge-client"
DENIED_IDENTITY = "octryx-local-smoke-denied-client"
RETENTION_IDENTITY = "octryx-local-smoke-retention-client"
BUCKET = "octryx-local-smoke-knowledge"
ABSENT_BUCKET = "octryx-local-smoke-knowledge-absent"
UNRELATED_BUCKET = "octryx-local-smoke-unrelated"
EXPECTED_ACTIONS = {
    ADMIN_IDENTITY: ["Admin", "Read", "Write", "List"],
    CLIENT_IDENTITY: [
        f"Read:{BUCKET}",
        f"Write:{BUCKET}",
        f"Read:{ABSENT_BUCKET}",
        f"Write:{ABSENT_BUCKET}",
    ],
    DENIED_IDENTITY: [f"Read:{UNRELATED_BUCKET}", f"Write:{UNRELATED_BUCKET}"],
    # list and delete inside the bucket, and no Read grant at all.
    RETENTION_IDENTITY: [f"List:{BUCKET}", f"Write:{BUCKET}"],
}

# Fixed acceptance Workspaces: two distinct partitions of the same bytes.
WORKSPACE_1 = "3f2a9c6e-1b84-4d07-9a53-8c7e5d1f4b26"
WORKSPACE_2 = "c81d4e7a-5f30-4b92-8e6c-2a9f7d3b1c05"

STORED = b"octryx knowledge object protocol acceptance\n"
UNSTORED = b"octryx knowledge object that is never written\n"
ADDRESSED = b"octryx knowledge object content address\n"
PLANTED = b"bytes that do not hash to the address they were planted at\n"

# Product configuration variable names, quoted rather than imported so a rename
# in the product is a visible failure here instead of a silent behavior change.
ENV_ENDPOINT_URL = "OCTRYX_KNOWLEDGE_OBJECT_ENDPOINT_URL"
ENV_BUCKET = "OCTRYX_KNOWLEDGE_OBJECT_BUCKET"
ENV_REGION = "OCTRYX_KNOWLEDGE_OBJECT_REGION"
ENV_PREFIX = "OCTRYX_KNOWLEDGE_OBJECT_PREFIX"
ENV_TIMEOUT_SECONDS = "OCTRYX_KNOWLEDGE_OBJECT_TIMEOUT_SECONDS"

MAX_IDENTITY_FILE_BYTES = 8192
_PORT = re.compile(r"^[1-9][0-9]{0,4}$")
_SECRET_KEY = re.compile(r"^[0-9a-f]{48}$")


class SmokeError(Exception):
    """A fixed, secret-free failure line."""


def report_pass(label: str) -> None:
    print(f"PASS {label}", flush=True)


def is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def port_from_environment() -> int:
    raw = os.environ.get("OBJECT_STORE_S3_PORT", "")
    if raw == "":
        return DEFAULT_PORT
    if not _PORT.fullmatch(raw) or int(raw) > 65535:
        raise SmokeError("configuration: OBJECT_STORE_S3_PORT must be a decimal port")
    return int(raw)


def product_config_mapping(port: int, bucket: str) -> Mapping[str, str]:
    """The explicit mapping the product validates for itself; no credential in it."""
    return {
        ENV_ENDPOINT_URL: f"http://{HOST}:{port}",
        ENV_BUCKET: bucket,
        ENV_REGION: REGION,
        ENV_PREFIX: PREFIX,
        ENV_TIMEOUT_SECONDS: "10",
    }


def _read_identity_bytes(checkout: Path) -> bytes:
    raw_path = os.environ.get("OBJECT_STORE_IDENTITIES_FILE", "")
    if raw_path == "":
        raise SmokeError("identity file: OBJECT_STORE_IDENTITIES_FILE is not set")
    if not os.path.isabs(raw_path):
        raise SmokeError("identity file: OBJECT_STORE_IDENTITIES_FILE must be absolute")
    real_path = Path(os.path.realpath(raw_path))
    if is_within(real_path, checkout):
        raise SmokeError("identity file: must live outside the repository")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(real_path, flags)
    except OSError:
        raise SmokeError("identity file: not readable") from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SmokeError("identity file: not a regular file")
        data = os.read(descriptor, MAX_IDENTITY_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_IDENTITY_FILE_BYTES:
        raise SmokeError("identity file: larger than the fixture ever writes")
    return data


def read_identities(checkout: Path) -> dict[str, str]:
    """Return the generated secret key of each fixture identity.

    The file that configures the server is the single source of the credentials,
    so the smoke and the runtime cannot drift apart; the grants are re-checked
    against :data:`EXPECTED_ACTIONS` so a widened grant fails the run instead of
    quietly making an authorization check pass. Nothing read here is printed.
    """
    data = _read_identity_bytes(checkout)
    try:
        document = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise SmokeError("identity file: not the ASCII JSON the fixture writes") from None
    secrets: dict[str, str] = {}
    entries = document.get("identities") if isinstance(document, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        credentials = entry.get("credentials")
        if name not in EXPECTED_ACTIONS or not isinstance(credentials, list):
            raise SmokeError("identity file: does not match the fixture's identities")
        if len(credentials) != 1 or entry.get("actions") != EXPECTED_ACTIONS[name]:
            raise SmokeError(f"identity file: grants of {name} are not the expected ones")
        credential = credentials[0]
        access_key = credential.get("accessKey") if isinstance(credential, dict) else None
        secret_key = credential.get("secretKey") if isinstance(credential, dict) else None
        if access_key != name or type(secret_key) is not str:
            raise SmokeError(f"identity file: credential of {name} is malformed")
        if not _SECRET_KEY.fullmatch(secret_key):
            raise SmokeError(f"identity file: credential of {name} is not a generated test key")
        secrets[name] = secret_key
    if set(secrets) != set(EXPECTED_ACTIONS):
        raise SmokeError("identity file: does not define exactly the fixture's identities")
    report_pass(
        "identity file: outside the repository, exactly the fixture's least-privilege grants"
    )
    return secrets


def neutralize_ambient_aws() -> None:
    """Make sure no real AWS identity or endpoint can be picked up.

    Development hosts carry real AWS profiles. The product resolves credentials
    from the boto3 default chain, so every other source of that chain is switched
    off before the first client exists: only the explicit fixture keys remain.
    """
    for name in (
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
        "AWS_ROLE_ARN",
        "AWS_ROLE_SESSION_NAME",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
        "AWS_ENDPOINT_URL",
        "AWS_ENDPOINT_URL_S3",
        "AWS_USE_FIPS_ENDPOINT",
        "AWS_USE_DUALSTACK_ENDPOINT",
    ):
        os.environ.pop(name, None)
    os.environ["AWS_CONFIG_FILE"] = os.devnull
    os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
    os.environ["AWS_DEFAULT_REGION"] = REGION
    report_pass("credential chain: only the generated fixture keys can be resolved")
