"""The administrative audit trail: one event per change.

``request_scope`` lets the request middleware skip its generic ``METHOD path`` row when the request already wrote a
domain audit event; ``categories`` decides which rows are administrative changes and under which category
Observability → Audit log shows them.
"""
