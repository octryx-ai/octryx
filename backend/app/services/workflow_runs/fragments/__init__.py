"""Workflow fragments: reusable, versioned sub-graphs compiled into a phased workflow at publish time.

A fragment is a flow version whose ``definition_json.execution_kind`` is ``phased_fragment`` (``format``). A
composite *source* names it through a ``fragment`` reference node pinned by checksum (and, on the API path, by
version id); ``compiler.compile_composite`` replaces every reference by the fragment's nodes and edges, so the stored
``definition_json`` of a composite version is an ordinary phased graph the runtime runs unchanged. ``validation``
judges a fragment on its own (through the same phased validator, in a synthetic harness) and a composed graph (the
compiled graph through the unchanged phased validator, plus the port, pin and input refusals of the compiler).
"""
