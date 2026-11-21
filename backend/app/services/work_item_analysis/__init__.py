"""Work item analysis: a governed, cited analysis of one Work Item, stored as an agent note.

Modules: ``settings`` (Workspace options), ``prompt`` (the versioned ``incident_analysis_v1`` template),
``contract`` (the structured analysis: validation, citation check, rendering), ``governed_run`` (the model
run with its read-only tool surface and cost cap), ``runner`` (``analyze_work_item``), ``reporter_questions``
(the optional Jira question), ``auto_start`` (opt-in automatic runs) and ``workflow_template``.
Kept import-free so the project-config owner hook can import ``settings`` without cycles.
"""
