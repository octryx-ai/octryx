"""Additive specification tool classes; existing shared handler supplies actual server context."""
from .workflow_outputs import _SubmitPhaseOutputTool


class SubmitIdeaFrameTool(_SubmitPhaseOutputTool):
    name = "submit_idea_frame"
    description = "Submit the workflow idea, scope and explicit questions for human confirmation."


class SubmitResearchPlanTool(_SubmitPhaseOutputTool):
    name = "submit_research_plan"
    description = "Submit Knowledge-only research questions; the server binds idea and effective run budget."


class SubmitResearchBriefTool(_SubmitPhaseOutputTool):
    name = "submit_research_brief"
    description = "Submit claims backed by actual current-pass Knowledge reads, contradictions and uncertainty."


class SubmitSpecTool(_SubmitPhaseOutputTool):
    name = "submit_spec"
    description = "Submit stories, Given/When/Then criteria and claims using the pinned research evidence."
