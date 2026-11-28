"""The fixed vocabulary of Octryx Mobile pairing and phone logins."""

from __future__ import annotations

from datetime import timedelta

# Short lifetimes bound the QR code's scan window, the Mac's confirmation and the first-start claim.
CODE_BYTES = 16
CODE_TTL = timedelta(minutes=2)
CONFIRM_TTL = timedelta(minutes=3)
CLAIM_TTL = timedelta(minutes=15)
SECRET_BYTES = 32
# Short enough to type when iOS does not hand it over; 40 bits suffice because it exists only after confirmation,
# lives 15 minutes, is redeemed once and failed claims are rate-limited per address.
CLAIM_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CLAIM_LENGTH = 8
# Short, so a revoked phone is cut off within minutes (the APIs check the phone on every request, see ``session``).
ACCESS_TOKEN_TTL = timedelta(minutes=5)
ACCESS_CLAIM = "msid"  # == services.auth.service.PHONE_SESSION_CLAIM

# The phone's own credential: an httpOnly cookie only the mobile session routes ever see.
MOBILE_COOKIE = "octryx_mobile"
MOBILE_COOKIE_PATH = "/api/v1/mobile"
PAIR_PATH = "/m/pair"
CONFIRM_PATH = "/m/confirm"
REASON_BROWSER_REQUIRED = "mobile_confirm_in_browser"
REASON_LOGIN_REQUIRED = "mobile_pairing_login_required"

REASON_PAIRING_NOT_FOUND = "mobile_pairing_not_found"
REASON_PAIRING_EXPIRED = "mobile_pairing_expired"
REASON_PAIRING_USED = "mobile_pairing_used"
REASON_PAIRING_DENIED = "mobile_pairing_denied"
REASON_PAIRING_NOT_SCANNED = "mobile_pairing_not_scanned"
REASON_CLAIM_INVALID = "mobile_claim_invalid"
REASON_NOT_PAIRED = "mobile_not_paired"
REASON_REVOKED = "mobile_device_revoked"
REASON_LOGIN_EXPIRED = "mobile_login_expired"
REASON_NOT_FOUND = "mobile_device_not_found"
REASON_RATE_LIMITED = "mobile_rate_limited"
REASON_BODY_INVALID = "request_body_invalid"
REASON_SURFACE = "mobile_surface_not_allowed"
REASON_TOO_MANY = "mobile_pairing_limit"
# At most this many pairings per user within the window (a stuck or scripted loop cannot flood the table).
PAIRING_LIMIT = 5
PAIRING_LIMIT_WINDOW = timedelta(minutes=10)

RATE_SCOPE_PAIRING = "mobile.pairing"
RATE_SCOPE_CLAIM = "mobile.claim"
RATE_SCOPE_SESSION = "mobile.session"

AUDIT_PAIRING_CREATED = "mobile.pairing.created"
AUDIT_PAIRING_SCANNED = "mobile.pairing.scanned"
AUDIT_PAIRING_CONFIRMED = "mobile.pairing.confirmed"
AUDIT_PAIRING_DENIED = "mobile.pairing.denied"
AUDIT_DEVICE_PAIRED = "mobile.device.paired"
AUDIT_DEVICE_REVOKED = "mobile.device.revoked"

__all__ = [name for name in dir() if name.isupper()]
