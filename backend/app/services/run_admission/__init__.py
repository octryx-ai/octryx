"""What a run may start: the published phased workflows, and an Action's either/or rule.

A phased workflow starts as a workflow run for a Work item (``phased_catalog``); an archived or
switched-off phased workflow is refused with the typed ``denied: workflow_archived``
(``archived_workflows``); an Action names either a workflow run or an agent with a prompt, never
both (``action_config``). The closed denial vocabulary is ``denials``.
"""
