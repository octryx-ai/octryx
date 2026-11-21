"""Full session transcripts per Workspace switch: ingest, redaction, read access, retention.

- ``redaction``: the platform's second secret pass over every stored and every served line;
- ``store``: one launcher batch -> one gzip JSON-lines object in the artifact store + one index row;
- ``access``: who may list and read (Workspace admins and owners, the session's owner), audited per read;
- ``retention``: the purge on the workflow sweep's tick.
"""
