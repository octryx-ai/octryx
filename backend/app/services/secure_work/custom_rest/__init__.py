"""Custom REST as a Work source.

A Custom REST definition's list operation is synced into Work items on the shared intake pipeline
(``intake/pipeline``), on a schedule or when an inbound webhook bound to the intake's task fires:

- ``config``: the intake's operation, role, field mapping (dotted paths), status mapping, closed statuses, limits;
- ``listing``: the pages, read through the REST executor as the intake's role (its data scope and result filter);
- ``records``: a record -> a Work item payload (stable key required, bounded texts, the reporter an identifier);
- ``intake``: save, schedule, run; ``intake_source``: the registry adapter (setup, discovery, sample);
- ``write_back``: the state write-back through a write operation of the definition, by a person only.
"""
