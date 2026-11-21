"""Workflow B's documentation phase.

After the merge watch the phase's agent drafts the feature documentation as a structured output
(``feature_documentation``: what, why, how to use); the requester confirms the page the server renders from it and
from the run's recorded facts (the confirmed test contract's acceptance criteria → tests, the ticket and pull
request links); the platform publishes and proves it through the publish & prove steps (``s1_graph``) and records
the page on the run and the Work item.

- ``record``: the output kind and its validation;
- ``page``: the Workspace's documentation settings, the page title and the rendered storage body;
- ``publish``: the record of a published page on the run and the Work item;
- ``knowledge``: the Knowledge sync of the published version and its proof against the sync ledger;
- ``flow``: the data-flow rules (producers, consumers, publish only after the requester's confirmation).
"""
