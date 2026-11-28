"""Classification level and PII type names shared by PII redaction and the classification policy."""

from __future__ import annotations

from typing import Final

CLASSIFICATION_CONFIDENTIAL: Final[str] = "confidential"

PII_EMAIL: Final[str] = "email"
PII_PHONE: Final[str] = "phone"
PII_SSN: Final[str] = "ssn"
PII_CREDIT_CARD: Final[str] = "credit_card"
PII_IBAN: Final[str] = "iban"
PII_IP_ADDRESS: Final[str] = "ip_address"
PII_NATIONAL_ID: Final[str] = "national_id"
