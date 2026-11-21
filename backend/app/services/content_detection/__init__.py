"""Content detection: generic detectors that find sensitive data; Cedar policies decide what happens.

- ``vocabulary``: categories, built-in detectors, mask styles, sources;
- ``validators``: mod 10 check digit, IBAN mod-97;
- ``builtin``: the built-in detectors (RE2 candidates + validators);
- ``scanner``: a request's segments scanned inside a size and time budget → ``ScanReport``;
- ``masking``: one-way placeholders, numbered per conversation.
"""
