"""The fixed vocabulary of content detection: categories, built-in detectors, mask styles, sources."""

from __future__ import annotations

from dataclasses import dataclass

CATEGORY_SECRETS = "secrets"
CATEGORY_PII = "pii"
CATEGORY_HEALTH = "health"
CATEGORY_CONFIDENTIAL_IDENTIFIER = "confidential_identifier"
CATEGORY_INTERNAL_NETWORK = "internal_network"
CATEGORY_PROMPT_INJECTION = "prompt_injection"

DETECTOR_IBAN = "iban"
DETECTOR_EMAIL = "email"
DETECTOR_PHONE = "phone"
DETECTOR_SECRETS = "secrets"
DETECTOR_CREDENTIAL_ASSIGNMENT = "credential_assignment"
DETECTOR_INTERNAL_IP = "internal_ip"
DETECTOR_PROMPT_INJECTION = "prompt_injection"
CUSTOM_PREFIX = "custom."

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"

MASK_LAST4 = "last4"
MASK_TYPE_TOKEN = "type_token"
MASK_COUNTRY_LAST4 = "country_last4"
MASK_FULL = "full"
MASK_STYLES: tuple[str, ...] = (MASK_LAST4, MASK_TYPE_TOKEN, MASK_COUNTRY_LAST4, MASK_FULL)

SOURCE_SYSTEM = "system"
SOURCE_PROMPT = "prompt"
SOURCE_TOOL_RESULT = "tool_result"
SOURCE_DOCUMENT = "document"
SOURCE_HISTORY = "history"
SOURCES: tuple[str, ...] = (SOURCE_SYSTEM, SOURCE_PROMPT, SOURCE_TOOL_RESULT, SOURCE_DOCUMENT, SOURCE_HISTORY)


@dataclass(frozen=True, slots=True)
class Category:
    id: str
    label: str
    note: str = ""
    builtin: bool = True

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "label": self.label, "note": self.note, "builtin": self.builtin}


@dataclass(frozen=True, slots=True)
class DetectorInfo:
    id: str
    category: str
    label: str
    token: str
    method: str
    confidence: str
    mask_styles: tuple[str, ...]
    builtin: bool = True

    @property
    def default_mask_style(self) -> str:
        return self.mask_styles[0]

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "category": self.category, "label": self.label, "method": self.method,
                "confidence": self.confidence, "mask_styles": list(self.mask_styles), "builtin": self.builtin}


BUILTIN_CATEGORIES: tuple[Category, ...] = (
    Category(CATEGORY_SECRETS, "Credentials"),
    Category(CATEGORY_PII, "Personal data"),
    Category(CATEGORY_HEALTH, "Health data",
             "No built-in detector: there is no reliable pattern. Add custom detectors of this category."),
    Category(CATEGORY_CONFIDENTIAL_IDENTIFIER, "Confidential identifiers",
             "Custom detectors only (for example customer, contract or case numbers)."),
    Category(CATEGORY_INTERNAL_NETWORK, "Internal network addresses"),
    Category(CATEGORY_PROMPT_INJECTION, "Prompt injection"),
)

BUILTIN_DETECTORS: tuple[DetectorInfo, ...] = (
    DetectorInfo(DETECTOR_IBAN, CATEGORY_PII, "IBAN", "IBAN",
                 "Country code, per-country length, ISO 7064 mod-97", "high", (MASK_COUNTRY_LAST4, MASK_TYPE_TOKEN)),
    DetectorInfo(DETECTOR_EMAIL, CATEGORY_PII, "Email address", "EMAIL", "local@domain.tld", "medium",
                 (MASK_TYPE_TOKEN,)),
    DetectorInfo(DETECTOR_PHONE, CATEGORY_PII, "Phone number", "PHONE",
                 "E.164, or a national number next to tel/phone/mobile/fax", "medium", (MASK_TYPE_TOKEN, MASK_LAST4)),
    DetectorInfo(DETECTOR_SECRETS, CATEGORY_SECRETS, "Credentials", "SECRET",
                 "The gateway secret scanner: private keys, cloud keys, vendor tokens, JWTs, bearer credentials, "
                 "URLs with a password; the kind is logged, never the value", "high", (MASK_TYPE_TOKEN,)),
    DetectorInfo(DETECTOR_CREDENTIAL_ASSIGNMENT, CATEGORY_SECRETS, "Credential assignment", "CREDENTIAL",
                 "A literal value assigned to password, api key, token or secret (not a variable or placeholder)",
                 "medium", (MASK_TYPE_TOKEN,)),
    DetectorInfo(DETECTOR_INTERNAL_IP, CATEGORY_INTERNAL_NETWORK, "Internal IP address", "INTERNAL_IP",
                 "IPv4 in 10/8, 172.16/12 or 192.168/16", "medium", (MASK_TYPE_TOKEN,)),
    DetectorInfo(DETECTOR_PROMPT_INJECTION, CATEGORY_PROMPT_INJECTION, "Prompt injection", "INJECTION",
                 "Instruction-override phrases: ignore previous instructions, jailbreak / DAN / developer mode, "
                 "you are now, act as, pretend to be", "medium", (MASK_FULL,)),
)

BUILTIN_DETECTOR_IDS: frozenset[str] = frozenset(item.id for item in BUILTIN_DETECTORS)
BUILTIN_CATEGORY_IDS: frozenset[str] = frozenset(item.id for item in BUILTIN_CATEGORIES)
CUSTOM_MASK_STYLES: tuple[str, ...] = (MASK_TYPE_TOKEN, MASK_LAST4, MASK_FULL)


def builtin_detector(detector_id: str) -> DetectorInfo | None:
    return next((item for item in BUILTIN_DETECTORS if item.id == detector_id), None)


__all__ = [
    "BUILTIN_CATEGORIES",
    "BUILTIN_CATEGORY_IDS",
    "BUILTIN_DETECTORS",
    "BUILTIN_DETECTOR_IDS",
    "CATEGORY_CONFIDENTIAL_IDENTIFIER",
    "CATEGORY_HEALTH",
    "CATEGORY_INTERNAL_NETWORK",
    "CATEGORY_PROMPT_INJECTION",
    "CATEGORY_PII",
    "CATEGORY_SECRETS",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "CUSTOM_MASK_STYLES",
    "CUSTOM_PREFIX",
    "DETECTOR_CREDENTIAL_ASSIGNMENT",
    "DETECTOR_EMAIL",
    "DETECTOR_IBAN",
    "DETECTOR_INTERNAL_IP",
    "DETECTOR_PHONE",
    "DETECTOR_PROMPT_INJECTION",
    "DETECTOR_SECRETS",
    "MASK_COUNTRY_LAST4",
    "MASK_FULL",
    "MASK_LAST4",
    "MASK_STYLES",
    "MASK_TYPE_TOKEN",
    "SOURCES",
    "SOURCE_DOCUMENT",
    "SOURCE_HISTORY",
    "SOURCE_PROMPT",
    "SOURCE_SYSTEM",
    "SOURCE_TOOL_RESULT",
    "Category",
    "DetectorInfo",
    "builtin_detector",
]
