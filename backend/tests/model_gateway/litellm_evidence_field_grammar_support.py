"""Shared helpers for the test_litellm_evidence_field_grammar_* modules."""

from __future__ import annotations

# Legitimate identifiers of the target environment that each carry ``sk-`` as a substring.
TARGET_ALIAS = "task-router"


TARGET_MODEL_GROUP = "desk-nova-lite"


TARGET_COST_REFERENCE = "desk-pricing-2026"


TARGET_ATTESTATION_REFERENCE = "litellm-posture-task-non-prod-2026-09-27"


TARGET_IDENTIFIERS = (
    TARGET_ALIAS,
    TARGET_MODEL_GROUP,
    TARGET_COST_REFERENCE,
    TARGET_ATTESTATION_REFERENCE,
)


# Hostile values, one per class the generic scan exists for, applied to every grammar-governed field.
REAL_KEY = ("sk-li" + "ve-4eC39HqLyjWDarjtT1zdp7dc")


AUTH_HEADER = "Authorization: Bearer 4eC39HqLyjWDarjtT1zdp7dc"


CREDENTIAL_URL = "https://virtual:sk-secret@litellm.shop-nonprod.example.com/v1"


SECRET_ASSIGNMENT = ("api_ke" + "y=4eC39HqLyjWDarjtT1zdp7dc")


PEM_BLOCK = "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBgkqhkiG9w0BAQ\n-----END PRIVATE KEY-----"


FREE_TEXT = "the operator will send the value to ops later"


GITLAB_TOKEN = ("glpat-Ab" + "CdEfGhIjKlMnOpQrSt")


SLACK_TOKEN = ("xoxb-12" + "34-5678-abcdefghijklmnop")


GITHUB_TOKEN = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345"
