"""Test vectors for the content detectors: published examples and synthetic text only.

The IBANs are the published registry examples; the mod-10 numbers are the textbook example of the check digit.
None of them belongs to a real account.
"""

# Mod 10 holds (the textbook example) / fails (last digit changed).
MOD10_VALID = "79927398713"
MOD10_INVALID = "79927398710"
TEST_IBANS: tuple[str, ...] = ("GB82WEST12345698765432", "DE89370400440532013000")
INVALID_IBAN = "DE89370400440532013001"
