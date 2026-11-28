"""Verified Kubernetes API TLS settings for typed reads and connection tests."""
from __future__ import annotations

import re
import ssl
from typing import Any

_CA_BLOCK = re.compile(r"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----")


class KubernetesTLSConfigurationError(ValueError):
    pass


def kubernetes_tls_verify(config: dict[str, Any], *, in_cluster_ca: str | None = None) -> bool | str | ssl.SSLContext:
    verify = config.get("k8s_verify_tls", True)
    value = config.get("k8s_ca_certificate")
    if value is None or value == "":
        return in_cluster_ca or verify
    if not isinstance(value, str):
        raise KubernetesTLSConfigurationError("k8s_ca_certificate must be a public PEM CA certificate bundle.")
    pem = value.strip()
    if not pem:
        return in_cluster_ca or verify
    if verify is not True:
        raise KubernetesTLSConfigurationError("A configured Kubernetes CA requires TLS verification "
                                             "(k8s_verify_tls=true).")
    blocks = _CA_BLOCK.findall(pem)
    if not blocks or _CA_BLOCK.sub("", pem).strip():
        raise KubernetesTLSConfigurationError("k8s_ca_certificate must contain only public PEM CA certificates.")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        context.load_verify_locations(cadata=pem)
    except (ssl.SSLError, ValueError) as error:
        raise KubernetesTLSConfigurationError("k8s_ca_certificate contains an invalid PEM CA certificate.") from error
    if not context.get_ca_certs():
        raise KubernetesTLSConfigurationError("k8s_ca_certificate contains no CA certificate.")
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


__all__ = ["KubernetesTLSConfigurationError", "kubernetes_tls_verify"]
