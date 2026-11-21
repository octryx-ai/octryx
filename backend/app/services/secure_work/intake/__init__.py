"""Work intake per Workspace: which items flow from the Workspace's
connections into Work, when, and how.

- ``connections``: the Workspace's connections of a work source (its default entry and its named connections);
- ``overview``: one row per source (Connection · In Knowledge · In Work) and the Workspace's intakes;
- ``runs``: the run history of one intake and the trigger of a run.

An intake never declares a connection, URL, credential or project allowlist; it picks from the Workspace's.
"""
