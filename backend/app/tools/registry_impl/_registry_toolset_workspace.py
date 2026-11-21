"""Tool classes: knowledge, workspace runtime, code quality, browser, Office and scripts."""

from __future__ import annotations

from app.tools.browser import (
    BrowserClickTool,
    BrowserCloseTool,
    BrowserOpenUrlTool,
    BrowserPressTool,
    BrowserScreenshotTool,
    BrowserSnapshotTool,
    BrowserTypeTool,
)
from app.tools.documents import IngestDocumentSourceTool, QueryDocumentKnowledgeTool
from app.tools.knowledge_evidence.changes import KnowledgeChangesTool
from app.tools.knowledge_evidence.code_impact import KnowledgeCodeImpactTool
from app.tools.knowledge_evidence.confluence_updates import ListConfluencePageUpdatesTool
from app.tools.knowledge_evidence.episode_summary import KnowledgeEpisodeSummaryTool
from app.tools.knowledge_evidence.read import KnowledgeReadTool
from app.tools.knowledge_evidence.search import KnowledgeSearchTool
from app.tools.knowledge_evidence.structured_graph import ConfigVsManualTool, GraphNeighborsTool, OpsChainTool
from app.tools.knowledge_impl._engineering_knowledge_tools import (
    AddPackItemTool,
    BuildEngineeringKnowledgePackTool,
    CreatePackDraftTool,
    FinalizePackDraftTool,
    GetEngineeringKnowledgePackTool,
    GetPipelineFailurePatternsTool,
    GetRepositoryPatternsTool,
    GetReviewerExpertiseTool,
    GetVulnerabilityFixKnowledgeTool,
    ResolveEngineeringKnowledgePackTool,
    RetrieveEngineeringKnowledgePackRecordsTool,
    SearchEngineeringKnowledgePacksTool,
    SearchEngineeringKnowledgeTool,
)
from app.tools.knowledge_impl._knowledge_fetch import FetchAndSaveKnowledgeTool
from app.tools.knowledge_impl._knowledge_retrieve import KnowledgeRetrieveTool
from app.tools.knowledge_memory.recall import MemoryRecallTool
from app.tools.knowledge_memory.remember import MemoryRememberTool
from app.tools.office_impl._office_basic import (
    AddOfficeElementTool,
    CreateOfficeDocumentTool,
    FillOfficeTemplateTool,
    GetOfficeDocumentInfoTool,
    GetOfficeElementTool,
    QueryOfficeElementsTool,
    ReadOfficeDocumentTool,
    RemoveOfficeElementTool,
    SetOfficePropertyTool,
    ValidateOfficeDocumentTool,
)
from app.tools.office_impl._office_excel_scripts import (
    BuildExcelTemplateScriptTool,
    CreateExcelChartTool,
    GetPresentationHtmlTool,
    ReadExcelCellTool,
    SetExcelCellTool,
)
from app.tools.office_impl._office_presentation_script import BuildPresentationScriptTool
from app.tools.office_impl._office_word_scripts import BuildWordTemplateScriptTool
from app.tools.python_runtime import PythonCloseSessionTool, PythonExecCodeTool, PythonListVariablesTool
from app.tools.runtime_impl._runtime_code import (
    CodeCallersTool,
    CodeFileOutlineTool,
    CodeImpactAnalysisTool,
    CodeIndexRepositoryTool,
    CodeIntelligenceStatusTool,
    CodeReferencesTool,
    CodeSearchRepositoryTool,
    CodeSymbolDefinitionTool,
)
from app.tools.runtime_impl._runtime_code_git_tools import (
    BuildPullRequestDescriptionTool,
    GitChangeSummaryTool,
    GitConflictPredictorTool,
    GitCouplingMapTool,
    GitFileIntelligenceTool,
    GitFunctionBlameTool,
    GitHotspotAnalysisTool,
    GitKnowledgeExtractTool,
    GitPrContextTool,
    SelfReviewWorkspaceDiffTool,
)
from app.tools.runtime_impl._runtime_code_graph_tools import (
    CodeAffectedTool,
    CodeCalleesTool,
    CodeContextTool,
    CodeExploreTool,
    CodeFilesTool,
    CodeGodNodesTool,
    CodeGraphStatsTool,
    CodeGraphStatusTool,
    CodeGraphSummaryTool,
    CodeImpactTool,
    CodeNeighborsTool,
    CodeNodeTool,
    CodeTraceTool,
)
from app.tools.runtime_impl._runtime_design_tools import (
    GetProjectDesignContextTool,
    GetProjectDesignReadinessTool,
    GetProjectDesignTraceabilityTool,
    ListProjectDesignArtifactsTool,
    RunDesignTraceSyncWorkflowTool,
)
from app.tools.runtime_impl._runtime_kubectl_tool import RunKubectlCommandTool
from app.tools.runtime_impl._runtime_quality_tools_code import (
    AnalyzeCodebasePatternsTool,
    GetRepoCodeQualityConfigTool,
    LintAndFormatWorkspaceTool,
    RunOpenRewriteRecipeTool,
    RunSastSuiteTool,
)
from app.tools.runtime_impl._runtime_quality_tools_vcs import GetGitDiffTool, ListWorkspaceGitCommitsTool
from app.tools.runtime_impl._runtime_readme_status_tool import ListRepositoryReadmeStatusTool
from app.tools.runtime_impl._runtime_repo_analysis_collection import GenerateRepositoryReadmesTool
from app.tools.runtime_impl._runtime_repo_analysis_overview import AnalyzeWorkspaceRepositoryTool
from app.tools.runtime_impl._runtime_saved_script_tools import (
    GetSavedPythonScriptTool,
    ListSavedPythonScriptsTool,
    RunSavedPythonScriptTool,
    SavePythonScriptTool,
)
from app.tools.runtime_impl._runtime_test_suite_tool import RunTestSuiteTool
from app.tools.runtime_impl._runtime_validation_commands import RunValidationCommandsTool
from app.tools.runtime_impl._runtime_workspace_cli import RunCLICommandTool
from app.tools.runtime_impl._runtime_workspace_files import (
    ListWorkspaceDirectoryTool,
    ReadWorkspaceFileTool,
    WriteWorkspaceFileTool,
)
from app.tools.runtime_impl._runtime_workspace_http import HttpRequestTool
from app.tools.runtime_impl._runtime_workspace_processes import (
    CancelRuntimeProcessTool,
    CollectRuntimeProcessTool,
    PollRuntimeProcessTool,
    StartRuntimeProcessTool,
)
from app.tools.runtime_impl._runtime_workspace_system import (
    BootstrapWorkspaceRepositoryTool,
    GetCurrentTimeTool,
    GetSystemContextTool,
)
from app.tools.skills import SkillGetTool, SkillSearchTool

TOOL_CLASSES_WORKSPACE = [
    SearchEngineeringKnowledgeTool,
    GetRepositoryPatternsTool,
    GetVulnerabilityFixKnowledgeTool,
    GetPipelineFailurePatternsTool,
    GetReviewerExpertiseTool,
    KnowledgeRetrieveTool,
    KnowledgeSearchTool,
    KnowledgeReadTool,
    KnowledgeChangesTool,
    KnowledgeCodeImpactTool,
    GraphNeighborsTool,
    ConfigVsManualTool,
    OpsChainTool,
    KnowledgeEpisodeSummaryTool,
    ListConfluencePageUpdatesTool,
    MemoryRememberTool,
    MemoryRecallTool,
    SkillSearchTool,
    SkillGetTool,
    IngestDocumentSourceTool,
    QueryDocumentKnowledgeTool,
    FetchAndSaveKnowledgeTool,
    BuildEngineeringKnowledgePackTool,
    SearchEngineeringKnowledgePacksTool,
    RetrieveEngineeringKnowledgePackRecordsTool,
    GetEngineeringKnowledgePackTool,
    ResolveEngineeringKnowledgePackTool,
    CreatePackDraftTool,
    AddPackItemTool,
    FinalizePackDraftTool,
    HttpRequestTool,
    GetSystemContextTool,
    GetCurrentTimeTool,
    BootstrapWorkspaceRepositoryTool,
    CodeIntelligenceStatusTool,
    ListProjectDesignArtifactsTool,
    GetProjectDesignContextTool,
    GetProjectDesignReadinessTool,
    GetProjectDesignTraceabilityTool,
    RunDesignTraceSyncWorkflowTool,
    CodeIndexRepositoryTool,
    CodeSearchRepositoryTool,
    CodeSymbolDefinitionTool,
    CodeReferencesTool,
    CodeCallersTool,
    CodeCalleesTool,
    CodeAffectedTool,
    CodeImpactTool,
    CodeContextTool,
    CodeExploreTool,
    CodeFileOutlineTool,
    CodeFilesTool,
    CodeGraphSummaryTool,
    CodeGraphStatsTool,
    CodeGraphStatusTool,
    CodeGodNodesTool,
    CodeImpactAnalysisTool,
    CodeNeighborsTool,
    CodeNodeTool,
    CodeTraceTool,
    RunCLICommandTool,
    StartRuntimeProcessTool,
    PollRuntimeProcessTool,
    CollectRuntimeProcessTool,
    CancelRuntimeProcessTool,
    BuildPullRequestDescriptionTool,
    GetRepoCodeQualityConfigTool,
    RunOpenRewriteRecipeTool,
    RunSastSuiteTool,
    RunTestSuiteTool,
    RunValidationCommandsTool,
    LintAndFormatWorkspaceTool,
    WriteWorkspaceFileTool,
    ListWorkspaceDirectoryTool,
    ReadWorkspaceFileTool,
    AnalyzeWorkspaceRepositoryTool,
    AnalyzeCodebasePatternsTool,
    GenerateRepositoryReadmesTool,
    ListRepositoryReadmeStatusTool,
    ListWorkspaceGitCommitsTool,
    GetGitDiffTool,
    BrowserOpenUrlTool,
    BrowserSnapshotTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserPressTool,
    BrowserScreenshotTool,
    BrowserCloseTool,
    BuildWordTemplateScriptTool,
    BuildExcelTemplateScriptTool,
    BuildPresentationScriptTool,
    CreateOfficeDocumentTool,
    ReadOfficeDocumentTool,
    GetOfficeDocumentInfoTool,
    ValidateOfficeDocumentTool,
    GetOfficeElementTool,
    QueryOfficeElementsTool,
    SetOfficePropertyTool,
    AddOfficeElementTool,
    RemoveOfficeElementTool,
    FillOfficeTemplateTool,
    ReadExcelCellTool,
    SetExcelCellTool,
    CreateExcelChartTool,
    GetPresentationHtmlTool,
    PythonExecCodeTool,
    PythonListVariablesTool,
    PythonCloseSessionTool,
    GitFileIntelligenceTool,
    GitCouplingMapTool,
    GitChangeSummaryTool,
    GitFunctionBlameTool,
    GitConflictPredictorTool,
    GitHotspotAnalysisTool,
    GitKnowledgeExtractTool,
    GitPrContextTool,
    SelfReviewWorkspaceDiffTool,
    RunKubectlCommandTool,
    SavePythonScriptTool,
    ListSavedPythonScriptsTool,
    GetSavedPythonScriptTool,
    RunSavedPythonScriptTool,
]
