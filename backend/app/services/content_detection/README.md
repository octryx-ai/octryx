# Content detection

Detectors find sensitive data in text. What happens to a finding is decided elsewhere: content handling
(`content_security`) and Cedar.

## Invariants

- Built-in and custom detector patterns are compiled with RE2 (`builtin.py`, `custom.py`).
- A custom detector set is accepted or refused whole (`custom_validation.check_detector_set`).
- A custom detector with a Workspace scope runs only in that Workspace (`registry.detector_set_for`).
- `ScanReport.summary()` holds detector ids, counts, categories and sources, never a matched value or span
  (`scanner.py`).
- Only a finished examination without findings is clean, and only a clean one enters a `CleanCache`
  (`examination.py`).
- Masking is one-way: no vault and no unmasking (`masking.py`).
- The remedy rescan of a masked copy ignores only findings entirely inside masker-generated placeholder characters
  of that same text object, never retained input (`content_routing.decision.scan_for`, `masking.Span`).
- `final_check.examine_request` raises `FinalCheckRefused` or returns the serialized payload it examined.
