"""Test-only TLS material for the local qualification fixture.

The qualification has to run over a real TLS handshake, otherwise the private-CA
trust decision is never exercised. A throwaway CA and one server certificate are
generated per run into a directory outside the repository, mode ``0700`` with
``0600`` files, and deleted by ``fixture.sh`` afterwards.

Nothing here is a product credential: the key exists for one loopback process and
for a few seconds. It must never be committed, reused, or copied into a provider
configuration.
"""

from __future__ import annotations

import ipaddress
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CA_COMMON_NAME = "Octryx Local LiteLLM Fixture CA"
# A distinct subject, so a check can assert *which* anchors a built trust store
# actually holds instead of only whether the handshake succeeded.
FOREIGN_CA_COMMON_NAME = "Octryx Local LiteLLM Fixture Foreign CA"
SERVER_COMMON_NAME = "localhost"
VALIDITY = timedelta(hours=1)


@dataclass(frozen=True)
class TlsMaterial:
    directory: Path
    ca_bundle_path: Path
    server_certificate_path: Path
    server_key_path: Path
    # A second, unrelated CA bundle. A client that trusts only this one must fail
    # the handshake, which is how "the configured bundle is the trust store" is
    # proven rather than assumed.
    foreign_ca_bundle_path: Path


def _write_private(path: Path, payload: bytes) -> None:
    with open(path, "wb", opener=lambda p, flags: os.open(p, flags, stat.S_IRUSR | stat.S_IWUSR)) as handle:
        handle.write(payload)


def _ca(common_name: str = CA_COMMON_NAME) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def generate_tls_material(directory: Path) -> TlsMaterial:
    """Generate a CA, a ``localhost`` server certificate, and a foreign CA."""

    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, stat.S_IRWXU)

    ca_key, ca_certificate = _ca()
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, SERVER_COMMON_NAME)]))
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + VALIDITY)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(SERVER_COMMON_NAME),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    ca_bundle_path = directory / "fixture-ca.pem"
    server_certificate_path = directory / "fixture-server.pem"
    server_key_path = directory / "fixture-server.key"
    foreign_ca_bundle_path = directory / "foreign-ca.pem"

    _write_private(ca_bundle_path, ca_certificate.public_bytes(serialization.Encoding.PEM))
    _write_private(server_certificate_path, server_certificate.public_bytes(serialization.Encoding.PEM))
    _write_private(
        server_key_path,
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    _, foreign_certificate = _ca(FOREIGN_CA_COMMON_NAME)
    _write_private(foreign_ca_bundle_path, foreign_certificate.public_bytes(serialization.Encoding.PEM))

    return TlsMaterial(
        directory=directory,
        ca_bundle_path=ca_bundle_path,
        server_certificate_path=server_certificate_path,
        server_key_path=server_key_path,
        foreign_ca_bundle_path=foreign_ca_bundle_path,
    )


__all__ = [
    "CA_COMMON_NAME",
    "FOREIGN_CA_COMMON_NAME",
    "SERVER_COMMON_NAME",
    "TlsMaterial",
    "generate_tls_material",
]
