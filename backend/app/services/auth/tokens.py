"""Passwords and platform tokens: hashing, issuing and decoding access, stream and refresh-token hashes."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import bcrypt
import jwt
from fastapi import HTTPException, Request, status

from app.exceptions.api import AuthenticationError

from ...auth_cookie_policy import ACCESS_TOKEN_COOKIE, PHONE_ACCESS_COOKIE
from ...bcrypt_cost import bcrypt_salt
from ...config import get_settings
from ...time_utils import utc_now_aware

settings = get_settings()
JWT_ALGORITHM = "HS256"
SESSION_STREAM_TOKEN_SCOPE = "session_stream"
# JWT audience and issuer constants
JWT_AUDIENCE = "octryx-api"
JWT_ISSUER = "octryx-backend"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt_salt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> str:
    expire = utc_now_aware() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    payload = {"sub": user_id, "exp": expire, "aud": JWT_AUDIENCE, "iss": JWT_ISSUER}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def create_session_stream_token(
    *,
    user_id: str,
    session_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    expire = utc_now_aware() + (expires_delta or timedelta(minutes=10))
    payload = {
        "sub": user_id,
        "sid": session_id,
        "scope": SESSION_STREAM_TOKEN_SCOPE,
        "exp": expire,
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def _hash_refresh_token(token: str) -> str:
    # bcrypt-of-sha256 — bcrypt work-factor prevents brute-force; sha256 fits 72B bcrypt limit
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return bcrypt.hashpw(digest, bcrypt_salt()).decode("utf-8")


def _verify_refresh_token_bcrypt(token: str, stored_hash: str) -> bool:
    try:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        return bcrypt.checkpw(digest, stored_hash.encode("utf-8"))
    except Exception:
        return False


# A paired phone's access token (Octryx Mobile) names the phone; only the callers that check the phone in the
# database (``get_current_user`` and the chat API principal) accept it. Session stream tokens carry ``scope`` and
# ``sid``: they open one session's stream and are never a web access token.
PHONE_SESSION_CLAIM = "msid"
_NOT_WEB_ACCESS_CLAIMS = ("scope", "sid", "client_id", "grant_id")


def _web_access_claims(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM], audience=JWT_AUDIENCE,
                         issuer=JWT_ISSUER)
    if any(payload.get(claim) for claim in _NOT_WEB_ACCESS_CLAIMS):
        raise jwt.InvalidTokenError("not a web access token")
    return payload


def decode_token(token: str, *, allow_phone: bool = False) -> str:
    try:
        payload = _web_access_claims(token)
        user_id: str = payload.get("sub")
        if user_id is None or (payload.get(PHONE_SESSION_CLAIM) and not allow_phone):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return user_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _cookie_token_kind(token: str) -> str:
    try:
        payload = _web_access_claims(token)
    except jwt.PyJWTError:
        return ""
    if not payload.get("sub"):
        return ""
    return "phone" if payload.get(PHONE_SESSION_CLAIM) else "web"


def cookie_access_token(request: Request) -> str:
    web = str(request.cookies.get(ACCESS_TOKEN_COOKIE) or "").strip()
    if web and _cookie_token_kind(web) == "web":
        return web
    phone = str(request.cookies.get(PHONE_ACCESS_COOKIE) or "").strip()
    if phone and _cookie_token_kind(phone) == "phone":
        return phone
    return "" if web and _cookie_token_kind(web) == "phone" else web


def decode_session_stream_token(token: str) -> tuple[str, str]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
        )
        if payload.get("scope") != SESSION_STREAM_TOKEN_SCOPE:
            raise AuthenticationError("Invalid session stream token")
        user_id = str(payload.get("sub") or "").strip()
        session_id = str(payload.get("sid") or "").strip()
        if not user_id or not session_id:
            raise AuthenticationError("Invalid session stream token")
        return user_id, session_id
    except jwt.PyJWTError:
        raise AuthenticationError("Invalid session stream token")


async def verify_ws_token(token: str) -> str:
    try:
        payload = _web_access_claims(token)
        user_id: str = payload.get("sub")
        if user_id is None or payload.get(PHONE_SESSION_CLAIM):
            raise AuthenticationError("Invalid token")
        return user_id
    except jwt.PyJWTError:
        raise AuthenticationError("Invalid token")
