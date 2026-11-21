"""Tool classes: sub-agents, workflow outputs, code edits, sessions and work items."""

from __future__ import annotations

from app.tools.client_parity_tools import CLIENT_RUN_TOOLS
from app.tools.code_impl._code_edit import EditFileTool, MultiEditFileTool
from app.tools.code_impl._code_patch import ApplyPatchTool
from app.tools.code_impl._code_search import GlobFilesTool, GrepTool
from app.tools.code_impl._code_snapshot import (
    SnapshotCreateTool,
    SnapshotDiffRangeTool,
    SnapshotDiffStructuredTool,
    SnapshotDiffTool,
    SnapshotListTool,
    SnapshotRestoreTool,
)
from app.tools.code_impl._code_syntax import CheckFileSyntaxTool
from app.tools.code_structure import CodeStructureSnapshotTool
from app.tools.context_tools import (
    FreezeContextTool,
    GetSessionSummaryEvidenceTool,
    LoadToolArtifactTool,
    ReleaseContextTool,
)
from app.tools.instruction_tools import InstructionGetTool
from app.tools.proactive_teams_impl import AskReporterViaTeams
from app.tools.run_alert import GetRunAlert
from app.tools.runtime_impl._runtime_bash_web import BashTool, HtmlToMarkdownTool, WebFetchTool
from app.tools.runtime_impl._runtime_web_search_tools import WebSearchTool
from app.tools.secure_work_impl._work_item_tools import (
    WorkItemContextTool,
    WorkItemCreateTool,
    WorkItemLinkSessionTool,
    WorkItemNoteTool,
)
from app.tools.secure_work_impl._work_lifecycle_tools import (
    AgentPresenceListTool,
    BoardAckTool,
    BoardPostTool,
    BoardReadTool,
    ChangePlanDecideTool,
    ChangePlanGenerateTool,
    ChangeUnitsPlanTool,
    CodingAgentStartTool,
    CodingObservabilityTool,
    WhoIsWorkingOnTool,
    WorkItemClaimTool,
    WorkItemFindTool,
    WorkItemHandoffReadTool,
    WorkItemHandoffWriteTool,
    WorkItemListTool,
    WorkItemRedeclareTool,
    WorkItemReleaseTool,
    WorkItemTakeoverRequestTool,
    WorkItemTakeoverStatusTool,
    WorkItemTransitionTool,
)
from app.tools.session_tools import PlanExitTool, TodoReadTool, TodoWriteTool
from app.tools.specification_outputs import (
    SubmitIdeaFrameTool,
    SubmitResearchBriefTool,
    SubmitResearchPlanTool,
    SubmitSpecTool,
)
from app.tools.sub_agent import GetContextFromSubthreadsTool, SpawnSubAgentTool
from app.tools.workflow_outputs import (
    SubmitDefinitionOfReadyTool,
    SubmitFeatureDocumentationTool,
    SubmitIncidentHypothesisTool,
    SubmitPhaseResultTool,
    SubmitReproductionTool,
    SubmitSpecStudioTool,
    SubmitStoryPlanTool,
    SubmitTestContractTool,
    SubmitWorkPlanTool,
)
from app.tools.workflow_slices import DelegateSlicesTool, MergeSlicesTool
from app.tools.workflow_tools import ListAvailableWorkflowsTool, SelectWorkflowTool, StartWorkflowTool

TOOL_CLASSES_WORKFLOW = [
    SpawnSubAgentTool,
    GetContextFromSubthreadsTool,
    DelegateSlicesTool,
    MergeSlicesTool,
    GetRunAlert,
    SubmitDefinitionOfReadyTool,
    SubmitTestContractTool,
    SubmitReproductionTool,
    SubmitIncidentHypothesisTool,
    SubmitFeatureDocumentationTool,
    SubmitPhaseResultTool,
    SubmitWorkPlanTool,
    SubmitStoryPlanTool,
    SubmitSpecStudioTool,
    SubmitIdeaFrameTool,
    SubmitResearchPlanTool,
    SubmitResearchBriefTool,
    SubmitSpecTool,
    EditFileTool,
    MultiEditFileTool,
    GlobFilesTool,
    GrepTool,
    CodeStructureSnapshotTool,
    ApplyPatchTool,
    BashTool,
    HtmlToMarkdownTool,
    WebFetchTool,
    WebSearchTool,
    TodoReadTool,
    TodoWriteTool,
    PlanExitTool,
    FreezeContextTool,
    ReleaseContextTool,
    LoadToolArtifactTool,
    GetSessionSummaryEvidenceTool,
    ListAvailableWorkflowsTool,
    SelectWorkflowTool,
    StartWorkflowTool,
    InstructionGetTool,
    CheckFileSyntaxTool,
    SnapshotCreateTool,
    SnapshotRestoreTool,
    SnapshotDiffTool,
    SnapshotListTool,
    SnapshotDiffStructuredTool,
    SnapshotDiffRangeTool,
    # Platform work items (secure-work domain, never tracker-synced)
    WorkItemCreateTool,
    WorkItemContextTool,
    WorkItemNoteTool,
    WorkItemLinkSessionTool,
    # The Octryx client's work-item lifecycle in the chat
    WorkItemFindTool,
    WorkItemListTool,
    CodingObservabilityTool,
    WorkItemTransitionTool,
    ChangeUnitsPlanTool,
    ChangePlanGenerateTool,
    ChangePlanDecideTool,
    WorkItemRedeclareTool,
    CodingAgentStartTool,
    # Coordination between agents, the chat as its own agent
    AgentPresenceListTool,
    BoardAckTool,
    BoardPostTool,
    BoardReadTool,
    WhoIsWorkingOnTool,
    WorkItemClaimTool,
    WorkItemHandoffReadTool,
    WorkItemHandoffWriteTool,
    WorkItemReleaseTool,
    WorkItemTakeoverRequestTool,
    WorkItemTakeoverStatusTool,
    # The client's workflow-run, approval and task tools in the chat (gap B group 3)
    *CLIENT_RUN_TOOLS,
    # Proactive Teams
    AskReporterViaTeams,
]
