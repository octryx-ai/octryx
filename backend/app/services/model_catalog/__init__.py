"""The Model catalog (Runtime → Models → Model catalog).

One row per callable model (an ``llm_models`` row: a direct provider model or a gateway alias) with its General,
Data, Generation and Cost settings. Modules:

- ``clearance``: "cleared up to" and the per-level model lists the classification policy derives from it;
- ``views``: list/read rows with provider, usage, status and issues; ``usage``: order position, Workspaces;
- ``update``: save a row (``cost`` for the Cost tab), mirrored into the gateway alias (``alias_mirror``);
- ``sync``: refresh from the providers, flag vanished models, propose new ones (added inactive).
"""
