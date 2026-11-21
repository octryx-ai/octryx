"""Problems: one list of what is broken or needs attention, aggregated from existing status rows.

No storage of its own: one collector per kind reads the rows that already carry the state (``connections``,
``syncs``, ``intake``, ``runs``, ``denials``, ``tokens``, ``devices``, ``budgets``), ``service`` scopes, hides
acknowledged items and counts, ``links`` is the one place that says where each problem is fixed.
"""
