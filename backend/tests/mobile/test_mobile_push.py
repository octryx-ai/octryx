"""Octryx Mobile: notifications on the paired phone.

- the message is encrypted as RFC 8291 says: the phone (here a receiver built from the RFC) decrypts it; the VAPID
  header is an ES256 JWT for the push service's origin, verifiable with the public key the phone subscribed with;
- only HTTPS endpoints of known push services are accepted (no request to an arbitrary address);
- the sweep notifies each new entry once, by the phone's rules, never on the first look, never in quiet hours, with
  the "needs you" count as badge and a link to the entry; a gone subscription is deleted, a revoked phone gets none.
"""

# ruff: noqa: F811  (the shared ``configured`` fixture is imported, then requested by name)
from __future__ import annotations

import json
import struct

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select

from app.config import get_settings
from app.models import MobileDevice, MobilePushSubscription
from app.services.mobile import push
from app.services.mobile.webpush import GONE, SENT, b64url, encrypt, endpoint_allowed, unb64url, vapid_header
from tests.mobile.mobile_pairing_support import _cookie_header, _paired_phone
from tests.mobile.mobile_push_support import configured  # noqa: F401 - fixture

APPLE = "https://web.push.apple.com/QGuQyavXutnMH_example"


def _receiver():
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key, b64url(public), b64url(b"0123456789abcdef")


def _decrypt(body: bytes, key, p256dh: str, auth: str) -> bytes:
    salt, (record_size, id_len) = body[:16], struct.unpack("!IB", body[16:21])
    as_public, ciphertext = body[21:21 + id_len], body[21 + id_len:]
    assert record_size == 4096 and id_len == 65
    shared = key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    hkdf = lambda salt_, ikm, info, n: HKDF(algorithm=hashes.SHA256(), length=n, salt=salt_, info=info).derive(ikm)  # noqa: E731
    ikm = hkdf(unb64url(auth), shared, b"WebPush: info\x00" + unb64url(p256dh) + as_public, 32)
    cek = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_the_phone_decrypts_what_the_platform_encrypts():
    key, p256dh, auth = _receiver()
    message = json.dumps({"title": "Needs you", "body": "Approve: ./gradlew test"}).encode()
    body = encrypt(message, p256dh, auth)
    assert _decrypt(body, key, p256dh, auth) == message
    assert encrypt(message, p256dh, auth) != body  # a fresh salt and key every time


def test_the_vapid_header_is_a_verifiable_es256_token_for_the_push_origin():
    vapid_key = ec.generate_private_key(ec.SECP256R1())
    header = vapid_header(vapid_key, APPLE, "https://octryx.example.test", now=1_000_000)
    token, public = header.removeprefix("vapid t=").split(", k=")
    head, claims, signature = token.split(".")
    assert json.loads(unb64url(claims)) == {"aud": "https://web.push.apple.com", "exp": 1_000_000 + 12 * 3600,
                                            "sub": "https://octryx.example.test"}
    raw = unb64url(signature)
    verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64url(public))
    verifier.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                    f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


@pytest.mark.parametrize(("endpoint", "ok"), [
    (APPLE, True), ("https://fcm.googleapis.com/fcm/send/x", True), ("https://a.notify.windows.com/w/?t=x", True),
    ("http://web.push.apple.com/x", False), ("https://web.push.apple.com.evil.test/x", False),
    ("https://169.254.169.254/latest", False), ("https://user:pw@web.push.apple.com/x", False),
    ("https://web.push.apple.com:8443/x", False), (None, False), ("https://web.push.apple.com/a\nb", False),
    ("https://web.push.apple.com:99999/x", False), ("https://[web.push.apple.com/x", False),
])
def test_only_known_push_services_are_reachable(endpoint, ok):
    assert endpoint_allowed(endpoint) is ok


def _entry(key: str, severity: str = "action", kind: str = "device_approval", title: str = "Approve: tests"):
    return {"key": key, "kind": kind, "severity": severity, "title": title,
            "workspace": {"id": "ws-1", "name": "Acme Orders"}}


@pytest.mark.asyncio
async def test_subscribing_needs_configuration_and_a_known_push_service(client, db, monkeypatch):
    _user, _mac, claimed = await _paired_phone(client, db)
    phone = {"cookie": _cookie_header(claimed)}
    _key, p256dh, auth = _receiver()
    subscription = {"endpoint": APPLE, "keys": {"p256dh": p256dh, "auth": auth}}
    monkeypatch.setattr(get_settings(), "mobile_vapid_private_key", None)
    off = await client.put("/api/v1/mobile/push", json={"subscription": subscription}, headers=phone)
    assert off.status_code == 409 and off.json()["reason"] == "mobile_push_not_configured"
    assert (await client.get("/api/v1/mobile/push", headers=phone)).json()["configured"] is False


@pytest.mark.asyncio
async def test_a_phone_subscribes_sets_rules_and_unsubscribes(client, db, configured):
    _user, _mac, claimed = await _paired_phone(client, db)
    phone = {"cookie": _cookie_header(claimed)}
    state = (await client.get("/api/v1/mobile/push", headers=phone)).json()
    assert state["configured"] and state["public_key"] and not state["subscribed"]
    _key, p256dh, auth = _receiver()
    bad = await client.put("/api/v1/mobile/push", json={"subscription": {"endpoint": "https://evil.test/x",
                                                                          "keys": {"p256dh": p256dh, "auth": auth}}},
                           headers=phone)
    assert bad.status_code == 400
    done = await client.put("/api/v1/mobile/push", json={"subscription": {"endpoint": APPLE, "keys": {
        "p256dh": p256dh, "auth": auth}}, "rules": {"done": True}}, headers=phone)
    assert done.status_code == 200 and done.json()["subscribed"]
    assert done.json()["rules"] == {"needs_you": True, "problem": True, "done": True}
    rules = await client.put("/api/v1/mobile/push", json={"rules": {"problem": False}}, headers=phone)
    assert rules.json()["rules"] == {"needs_you": True, "problem": False, "done": True}  # the rest stays
    assert (await client.delete("/api/v1/mobile/push", headers=phone)).json()["subscribed"] is False


@pytest.mark.asyncio
async def test_the_sweep_notifies_each_new_entry_once_by_the_rules(client, db, configured, monkeypatch):
    user, _mac, claimed = await _paired_phone(client, db)
    device = (await db.execute(select(MobileDevice).where(MobileDevice.owner_user_id == user.id))).scalar_one()
    _key, p256dh, auth = _receiver()
    row = MobilePushSubscription(mobile_device_id=device.id, owner_user_id=user.id, endpoint=APPLE, p256dh=p256dh,
                                 auth=auth, rules=push.DEFAULT_RULES, notified=None)
    db.add(row)
    await db.flush()
    queue = {"items": [_entry("a:1")], "quiet": {"active": False}}

    async def fake_attention(_db, _user):
        return queue

    import app.services.attention.service as service

    monkeypatch.setattr(service, "attention", fake_attention)
    sent: list[dict] = []

    async def sender(_http, subscription, message, **kwargs):
        assert subscription.endpoint == APPLE and kwargs["subject"] == "https://octryx.example.test"
        sent.append({**message, "urgency": kwargs["urgency"]})
        return SENT

    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 0  # the first look takes note
    queue["items"] = [_entry("a:1"), _entry("a:2", title="Approve: deploy"), _entry("d:1", "info", "done"),
                      _entry("w:1", "warning", "problem", title="Run failed")]
    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 2
    assert [(item["title"], item["url"], item["badge"]) for item in sent] == [
        ("Needs you", "/m/#item=a:2", 2), ("Problem", "/m/#item=w:1", 2)]  # done is off by default
    assert sent[0]["urgency"] == "high" and sent[0]["body"] == "Approve: deploy · Acme Orders"
    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 0  # never twice

    queue["items"] = [*queue["items"], _entry("a:3")]
    queue["quiet"] = {"active": True}
    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 0  # quiet hours: silent
    queue["quiet"] = {"active": False}
    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 0  # and it stays silent after

    queue["items"] = [*queue["items"], *[_entry(f"b:{n}") for n in range(5)]]
    sent.clear()
    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 4
    assert sent[-1]["body"] == "and 2 more" and len(sent) == 4

    # An entry that leaves the queue and comes back (a run paused, resumed, paused) is not pushed again.
    sent.clear()
    queue["items"] = [item for item in queue["items"] if item["key"] != "a:2"]
    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 0
    queue["items"] = [*queue["items"], _entry("a:2", title="Approve: deploy")]
    assert await push.sweep_subscription(db, row, http=None, sender=sender) == 0 and sent == []


@pytest.mark.asyncio
async def test_a_gone_subscription_is_deleted_and_a_revoked_phone_gets_nothing(client, db, configured, monkeypatch):
    user, _mac, claimed = await _paired_phone(client, db)
    device = (await db.execute(select(MobileDevice).where(MobileDevice.owner_user_id == user.id))).scalar_one()
    _key, p256dh, auth = _receiver()
    row = MobilePushSubscription(mobile_device_id=device.id, owner_user_id=user.id, endpoint=APPLE, p256dh=p256dh,
                                 auth=auth, rules=push.DEFAULT_RULES, notified=[])

    async def fake_attention(_db, _user):
        return {"items": [_entry("a:9")], "quiet": {"active": False}}

    import app.services.attention.service as service

    monkeypatch.setattr(service, "attention", fake_attention)
    db.add(row)
    await db.flush()

    async def gone(*_args, **_kwargs):
        return GONE

    assert await push.sweep_subscription(db, row, http=None, sender=gone) == 0
    assert (await db.execute(select(MobilePushSubscription))).scalars().all() == []

    row = MobilePushSubscription(mobile_device_id=device.id, owner_user_id=user.id, endpoint=APPLE, p256dh=p256dh,
                                 auth=auth, rules=push.DEFAULT_RULES, notified=[])
    db.add(row)
    device.status = "revoked"
    await db.flush()

    async def never(*_args, **_kwargs):
        raise AssertionError("a revoked phone must get nothing")

    assert await push.sweep_subscription(db, row, http=None, sender=never) == 0
    assert (await db.execute(select(MobilePushSubscription))).scalars().all() == []  # and it is gone


@pytest.mark.asyncio
async def test_another_user_can_never_take_over_a_phones_subscription(client, db, configured):
    # The phone comes only from its own verified access cookie, never from a forged one riding
    # along with another login (bearer token, API key)
    import jwt

    from app.services.auth import create_access_token
    from app.services.mobile.contract import ACCESS_CLAIM

    bob, _mac, claimed = await _paired_phone(client, db, "bob-phone")
    bob_phone = (await db.execute(select(MobileDevice).where(MobileDevice.owner_user_id == bob.id))).scalar_one()
    _key, p256dh, auth = _receiver()
    mine = {"subscription": {"endpoint": APPLE, "keys": {"p256dh": p256dh, "auth": auth}}}
    assert (await client.put("/api/v1/mobile/push", json=mine, headers={"cookie": _cookie_header(claimed)})
            ).status_code == 200
    client.cookies.clear()
    alice, _mac_a, _claimed_a = await _paired_phone(client, db, "alice-phone")
    client.cookies.clear()
    forged = jwt.encode({"sub": str(bob.id), ACCESS_CLAIM: bob_phone.id}, "not-the-secret", algorithm="HS256")
    evil = {"subscription": {"endpoint": "https://web.push.apple.com/alice", "keys": {"p256dh": p256dh,
                                                                                       "auth": auth}}}
    for cookie in (forged, create_access_token(alice.id)):
        headers = {"authorization": f"Bearer {create_access_token(alice.id)}", "cookie": f"access_token={cookie}"}
        refused = await client.put("/api/v1/mobile/push", json=evil, headers=headers)
        assert refused.status_code == 403, refused.text
        assert (await client.delete("/api/v1/mobile/push", headers=headers)).json()["subscribed"] is False
    row = (await db.execute(select(MobilePushSubscription).where(
        MobilePushSubscription.mobile_device_id == bob_phone.id).execution_options(populate_existing=True))
           ).scalar_one()
    assert row.endpoint == APPLE  # Bob's subscription is untouched
