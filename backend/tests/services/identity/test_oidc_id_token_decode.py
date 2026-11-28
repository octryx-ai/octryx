"""The OIDC ID token check with PyJWT: the key comes from the provider's JWKS by exact kid with the token's RS algorithm.
aud, iss, exp, a foreign key and an HMAC token are refused; a slightly early iat is accepted."""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.services.oidc import id_token as oidc_service

ISSUER = "https://idp.example.test"
CLIENT_ID = "octryx-client"
PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FOREIGN = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(alg: str | None) -> dict:
    key = jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE.public_key(), as_dict=True)
    key["kid"] = "k1"
    if alg is not None:
        key["alg"] = alg
    return key


def _token(*, algorithm: str = "RS384", signer=PRIVATE, kid: str = "k1", **overrides) -> str:
    now = int(time.time())
    claims = {"aud": CLIENT_ID, "iss": ISSUER, "iat": now, "exp": now + 300, "sub": "person-1", "nonce": "n1"}
    claims.update(overrides)
    return jwt.encode(claims, signer, algorithm=algorithm, headers={"kid": kid})


async def _decode(monkeypatch, token: str, jwk: dict) -> dict:
    async def jwks(_uri: str) -> dict:
        return {"keys": [jwk]}

    monkeypatch.setattr(oidc_service, "_fetch_jwks", jwks)
    provider = SimpleNamespace(jwks_uri="https://idp.example.test/jwks", issuer_url=ISSUER, client_id=CLIENT_ID)
    return await oidc_service._decode_id_token_claims(provider=provider, config={}, id_token=token, nonce="n1")


@pytest.mark.parametrize("alg", [None, "RSA-OAEP", "RS384"])
async def test_an_rs384_token_verifies_whatever_alg_the_jwks_key_names(monkeypatch, alg):
    assert (await _decode(monkeypatch, _token(), _jwk(alg)))["sub"] == "person-1"


async def test_an_iat_a_few_seconds_ahead_is_accepted(monkeypatch):
    assert (await _decode(monkeypatch, _token(iat=int(time.time()) + 5), _jwk(None)))["sub"] == "person-1"


@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("foreign key", lambda: _token(signer=FOREIGN)),
        ("wrong audience", lambda: _token(aud="someone-else")),
        ("wrong issuer", lambda: _token(iss="https://evil.example.test")),
        ("expired", lambda: _token(exp=int(time.time()) - 5)),
        ("unknown kid", lambda: _token(kid="k2")),
        ("hmac token", lambda: jwt.encode({"aud": CLIENT_ID, "iss": ISSUER}, "x" * 40, algorithm="HS256",
                                          headers={"kid": "k1"})),
    ],
)
async def test_an_invalid_id_token_is_refused(monkeypatch, label, token):
    with pytest.raises(HTTPException) as refused:
        await _decode(monkeypatch, token(), _jwk(None))
    assert refused.value.status_code == 400, label
