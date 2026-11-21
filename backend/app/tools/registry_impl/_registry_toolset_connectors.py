"""Tool classes: Confluence and the external system connectors."""

from __future__ import annotations

from app.tools.confluence import (
    AddConfluenceComment,
    CreateConfluencePage,
    GetConfluencePage,
    ListConfluencePages,
    SearchConfluence,
    UpdateConfluencePage,
)
from app.tools.connectors.ansible import (
    CheckModeAnsiblePlaybookTool,
    GetAnsibleFactsTool,
    GetAnsibleJobOutputTool,
    ListAnsibleInventoryTool,
    RunAnsiblePlaybookTool,
)
from app.tools.connectors.argocd import (
    GetArgoCdAppStatusTool,
    GetArgoCdRolloutStatusTool,
    ListArgoCdAppsTool,
    ListArgoCdEventsTool,
    RollbackArgoCdAppTool,
    SyncArgoCdAppTool,
)
from app.tools.connectors.aws_compute import (
    GetAwsEc2LogsTool,
    ListAwsCloudWatchAlarmsTool,
    ListAwsEc2InstancesTool,
    ListAwsEksClustersTool,
    StartAwsEc2InstancesTool,
    StopAwsEc2InstancesTool,
)
from app.tools.connectors.aws_config_query import AwsConfigQueryTool
from app.tools.connectors.aws_cost_topology import AwsCostTopologyReportTool
from app.tools.connectors.aws_data import GetAwsRdsMetricsTool, GetAwsRdsSlowQueriesTool, ListAwsRdsInstancesTool
from app.tools.connectors.aws_deployment_timeline import AwsDeploymentTimelineTool
from app.tools.connectors.aws_exposure_map import AwsExposureMapTool
from app.tools.connectors.aws_gateway import AwsActionOperationTool, AwsReadOperationTool
from app.tools.connectors.aws_iac_drift import AwsRuntimeVsIacDriftTool
from app.tools.connectors.aws_incident_bundle import AwsIncidentEvidenceBundleTool
from app.tools.connectors.aws_lambda import (
    GetAwsCostByServiceTool,
    GetAwsLambdaLogsTool,
    InvokeAwsLambdaTool,
    ListAwsLambdaFunctionsTool,
    SearchAwsCloudTrailEventsTool,
)
from app.tools.connectors.aws_network_path import AwsNetworkPathAnalyzerTool
from app.tools.connectors.aws_pipeline import (
    GetAwsCodePipelineStateTool,
    GetAwsWafWebAclTool,
    ListAwsCodePipelineExecutionsTool,
    ListAwsCodePipelinesTool,
    ListAwsWafWebAclsTool,
    StartAwsCodePipelineExecutionTool,
)
from app.tools.connectors.aws_security_posture import AwsSecurityPostureSummaryTool
from app.tools.connectors.aws_topology import AwsTopologySnapshotTool
from app.tools.connectors.aws_topology_diff import AwsTopologyDiffTool
from app.tools.connectors.aws_trusted_advisor import AwsTrustedAdvisorSummaryTool
from app.tools.connectors.aws_well_architected import AwsWellArchitectedAssessmentTool
from app.tools.connectors.azure import (
    GetAzureCostTool,
    GetAzureMonitorAlertsTool,
    GetAzureMonitorMetricsTool,
    ListAzureAksClustersTool,
    ListAzureResourceGroupsTool,
    ListAzureVirtualMachinesTool,
    StartAzureVirtualMachineTool,
    StopAzureVirtualMachineTool,
)
from app.tools.connectors.azure_devops import ListAzureDevOpsPipelinesTool, ListAzureDevOpsWorkItemsTool
from app.tools.connectors.ci_artifacts import (
    CancelCiPipelineTool,
    GetCiArtifactTool,
    ListCiArtifactsTool,
    RetryCiJobTool,
    TriggerCiWorkflowTool,
)
from app.tools.connectors.ci_logs import GetCiJobLogsTool, GetCiPipelineLogsTool, GetCiTestResultsTool
from app.tools.connectors.datadog import (
    GetDatadogApmTracesTool,
    GetDatadogEventsTool,
    GetDatadogServiceMapTool,
    ListDatadogMonitorsTool,
    QueryDatadogMetricsTool,
)
from app.tools.connectors.elasticsearch import GetElasticsearchClusterHealthTool, SearchElasticsearchDocumentsTool
from app.tools.connectors.gcp import (
    GetGcpCloudRunLogsTool,
    GetGcpCloudSqlMetricsTool,
    GetGcpComputeLogsTool,
    ListGcpCloudRunServicesTool,
    ListGcpCloudSqlInstancesTool,
    ListGcpComputeInstancesTool,
    ListGcpGkeClustersTool,
    ListGcpProjectsTool,
)
from app.tools.connectors.github import ListGitHubActionRunsTool, ListGitHubPullRequestsTool, ListGitHubRepositoriesTool
from app.tools.connectors.github_commit_checks import GetGitHubCommitChecksTool
from app.tools.connectors.github_issues import (
    CreateGitHubIssueTool,
    GetGitHubIssueTool,
    ListGitHubIssuesTool,
    UpdateGitHubIssueTool,
)
from app.tools.connectors.github_pr_review import ListGitHubPullRequestHeadsTool, PostGitHubPullRequestReviewTool
from app.tools.connectors.github_pull_requests import (
    CreateGitHubPullRequestTool,
    GetGitHubPullRequestTool,
    UpdateGitHubPullRequestTool,
)
from app.tools.connectors.github_repository_create import CreateGitHubRepositoryTool
from app.tools.connectors.github_repository_prepare import PrepareGitHubRepositoryTool
from app.tools.connectors.github_repository_push import CommitAndPushGitHubRepositoryBranchTool
from app.tools.connectors.github_source_control import (
    CreateGitHubBranchTool,
    ListGitHubBranchesTool,
    ReadGitHubFileTool,
)
from app.tools.connectors.gitlab import ListGitLabMergeRequestsTool, ListGitLabPipelinesTool, ListGitLabProjectsTool
from app.tools.connectors.gitlab_commit_checks import GetGitLabCommitChecksTool
from app.tools.connectors.gitlab_merge_requests import (
    CreateGitLabMergeRequestTool,
    GetGitLabMergeRequestTool,
    UpdateGitLabMergeRequestTool,
)
from app.tools.connectors.gitlab_mr_review import ListGitLabMergeRequestHeadsTool, PostGitLabMergeRequestReviewTool
from app.tools.connectors.gitlab_repository_prepare import PrepareGitLabRepositoryTool
from app.tools.connectors.gitlab_repository_push import CommitAndPushGitLabRepositoryBranchTool
from app.tools.connectors.gitlab_source_control import (
    CreateGitLabBranchTool,
    ListGitLabBranchesTool,
    ReadGitLabFileTool,
)
from app.tools.connectors.helm import (
    GetHelmHistoryTool,
    GetHelmStatusTool,
    ListHelmReleasesTool,
    RollbackHelmReleaseTool,
    UpgradeHelmReleaseTool,
)
from app.tools.connectors.incidents import (
    AcknowledgeTool,
    CreateIncidentTool,
    EscalateTool,
    GetEscalationPolicyTool,
    GetScheduleTool,
    ListOnCallTool,
    ResolveTool,
)
from app.tools.connectors.issues import ListSonarQubeIssuesTool
from app.tools.connectors.ldap import (
    CheckLdapMembershipTool,
    GetLdapGroupsTool,
    LdapUserProvisioningTool,
    SearchLdapUserTool,
    SyncLdapUsersTool,
)
from app.tools.connectors.linear import CreateLinearIssueTool, UpdateLinearIssueTool
from app.tools.connectors.newrelic import GetNewRelicAlertsTool, GetNewRelicApmDataTool, QueryNewRelicNrqlTool
from app.tools.connectors.notion import GetNotionPageTool, SearchNotionPagesTool
from app.tools.connectors.outlook import (
    CheckOutlookAbsenceTool,
    CreateOutlookMeetingTool,
    FindNextOutlookSlotTool,
    GetOutlookFreeBusyTool,
    ListOutlookMeetingsTool,
    SendOutlookMeetingInviteTool,
)
from app.tools.connectors.registry import (
    DeleteRegistryTagTool,
    GetRegistryImageVulnerabilitiesTool,
    ListDockerRegistryRepositoriesTool,
    ListDockerRegistryTagsTool,
)
from app.tools.connectors.servicenow import (
    GetServiceNowRecordTool,
    ListServiceNowChangesTool,
    ListServiceNowIncidentsTool,
    ListServiceNowRecordsTool,
)
from app.tools.connectors.sharepoint import ListSharePointSitePagesTool, SearchSharePointTool
from app.tools.connectors.snyk import GetSnykFixAdviceTool, GetSnykSeverityTool, ListSnykVulnerabilitiesTool
from app.tools.connectors.sonarqube import GetSonarQubeProjectMetricsTool, GetSonarQubeQualityGateTool
from app.tools.connectors.splunk import GetSplunkIndexStatsTool, GetSplunkSavedSearchesTool, SearchSplunkLogsTool
from app.tools.connectors.statuspage import (
    ListStatuspageComponentsTool,
    ResolveStatuspageIncidentTool,
    UpdateIncidentTool,
    UpdateStatuspageComponentStatusTool,
)
from app.tools.connectors.terraform import (
    TerraformApplyTool,
    TerraformGetOutputTool,
    TerraformListResourcesTool,
    TerraformPlanTool,
    TerraformShowStateTool,
    TerraformWorkspaceSelectTool,
)
from app.tools.connectors.vault import (
    ListVaultSecretsTool,
    ReadVaultSecretTool,
    RenewVaultLeaseTool,
    RevokeVaultTokenTool,
    VaultAuditLogReadTool,
)

TOOL_CLASSES_CONNECTORS = [
    ListConfluencePages,
    GetConfluencePage,
    SearchConfluence,
    CreateConfluencePage,
    UpdateConfluencePage,
    AddConfluenceComment,
    ListDockerRegistryRepositoriesTool,
    ListDockerRegistryTagsTool,
    GetRegistryImageVulnerabilitiesTool,
    DeleteRegistryTagTool,
    SearchSplunkLogsTool,
    GetSplunkSavedSearchesTool,
    GetSplunkIndexStatsTool,
    CreateIncidentTool,
    EscalateTool,
    ListOnCallTool,
    AcknowledgeTool,
    ResolveTool,
    GetScheduleTool,
    GetEscalationPolicyTool,
    UpdateIncidentTool,
    ResolveStatuspageIncidentTool,
    ListStatuspageComponentsTool,
    UpdateStatuspageComponentStatusTool,
    ListHelmReleasesTool,
    GetHelmStatusTool,
    GetHelmHistoryTool,
    UpgradeHelmReleaseTool,
    RollbackHelmReleaseTool,
    SearchLdapUserTool,
    GetLdapGroupsTool,
    CheckLdapMembershipTool,
    SyncLdapUsersTool,
    LdapUserProvisioningTool,
    GetOutlookFreeBusyTool,
    ListOutlookMeetingsTool,
    CreateOutlookMeetingTool,
    FindNextOutlookSlotTool,
    CheckOutlookAbsenceTool,
    SendOutlookMeetingInviteTool,
    GetCiJobLogsTool,
    GetCiPipelineLogsTool,
    TriggerCiWorkflowTool,
    RetryCiJobTool,
    CancelCiPipelineTool,
    ListCiArtifactsTool,
    GetCiArtifactTool,
    GetCiTestResultsTool,
    GetSonarQubeProjectMetricsTool,
    ListSonarQubeIssuesTool,
    GetSonarQubeQualityGateTool,
    ListSnykVulnerabilitiesTool,
    GetSnykSeverityTool,
    GetSnykFixAdviceTool,
    QueryDatadogMetricsTool,
    ListDatadogMonitorsTool,
    GetDatadogEventsTool,
    GetDatadogApmTracesTool,
    GetDatadogServiceMapTool,
    QueryNewRelicNrqlTool,
    GetNewRelicAlertsTool,
    GetNewRelicApmDataTool,
    ListAzureDevOpsWorkItemsTool,
    ListAzureDevOpsPipelinesTool,
    CreateLinearIssueTool,
    UpdateLinearIssueTool,
    ListAnsibleInventoryTool,
    GetAnsibleFactsTool,
    RunAnsiblePlaybookTool,
    CheckModeAnsiblePlaybookTool,
    GetAnsibleJobOutputTool,
    ReadVaultSecretTool,
    ListVaultSecretsTool,
    RenewVaultLeaseTool,
    RevokeVaultTokenTool,
    VaultAuditLogReadTool,
    ListArgoCdAppsTool,
    GetArgoCdAppStatusTool,
    SyncArgoCdAppTool,
    GetArgoCdRolloutStatusTool,
    RollbackArgoCdAppTool,
    ListArgoCdEventsTool,
    TerraformPlanTool,
    TerraformApplyTool,
    TerraformShowStateTool,
    TerraformListResourcesTool,
    TerraformGetOutputTool,
    TerraformWorkspaceSelectTool,
    ListGitHubRepositoriesTool,
    CreateGitHubRepositoryTool,
    ReadGitHubFileTool,
    ListGitHubBranchesTool,
    CreateGitHubBranchTool,
    PrepareGitHubRepositoryTool,
    CommitAndPushGitHubRepositoryBranchTool,
    ListGitHubPullRequestsTool,
    GetGitHubPullRequestTool,
    CreateGitHubPullRequestTool,
    UpdateGitHubPullRequestTool,
    ListGitHubPullRequestHeadsTool,
    GetGitHubCommitChecksTool,
    PostGitHubPullRequestReviewTool,
    ListGitHubActionRunsTool,
    ListGitHubIssuesTool,
    GetGitHubIssueTool,
    CreateGitHubIssueTool,
    UpdateGitHubIssueTool,
    ListGitLabProjectsTool,
    ReadGitLabFileTool,
    ListGitLabBranchesTool,
    CreateGitLabBranchTool,
    PrepareGitLabRepositoryTool,
    CommitAndPushGitLabRepositoryBranchTool,
    ListGitLabMergeRequestsTool,
    GetGitLabMergeRequestTool,
    CreateGitLabMergeRequestTool,
    UpdateGitLabMergeRequestTool,
    ListGitLabPipelinesTool,
    ListGitLabMergeRequestHeadsTool,
    GetGitLabCommitChecksTool,
    PostGitLabMergeRequestReviewTool,
    SearchNotionPagesTool,
    GetNotionPageTool,
    SearchSharePointTool,
    ListSharePointSitePagesTool,
    ListServiceNowRecordsTool,
    GetServiceNowRecordTool,
    ListServiceNowIncidentsTool,
    ListServiceNowChangesTool,
    GetElasticsearchClusterHealthTool,
    SearchElasticsearchDocumentsTool,
    AwsReadOperationTool,
    AwsActionOperationTool,
    AwsConfigQueryTool,
    AwsCostTopologyReportTool,
    AwsDeploymentTimelineTool,
    AwsExposureMapTool,
    AwsIncidentEvidenceBundleTool,
    AwsNetworkPathAnalyzerTool,
    AwsRuntimeVsIacDriftTool,
    AwsSecurityPostureSummaryTool,
    AwsTopologyDiffTool,
    AwsTopologySnapshotTool,
    AwsTrustedAdvisorSummaryTool,
    AwsWellArchitectedAssessmentTool,
    ListAwsEksClustersTool,
    ListAwsCloudWatchAlarmsTool,
    ListAwsEc2InstancesTool,
    StartAwsEc2InstancesTool,
    StopAwsEc2InstancesTool,
    GetAwsEc2LogsTool,
    ListAwsRdsInstancesTool,
    GetAwsRdsMetricsTool,
    GetAwsRdsSlowQueriesTool,
    ListAwsLambdaFunctionsTool,
    GetAwsLambdaLogsTool,
    InvokeAwsLambdaTool,
    SearchAwsCloudTrailEventsTool,
    GetAwsCostByServiceTool,
    ListAwsCodePipelinesTool,
    GetAwsCodePipelineStateTool,
    ListAwsCodePipelineExecutionsTool,
    StartAwsCodePipelineExecutionTool,
    ListAwsWafWebAclsTool,
    GetAwsWafWebAclTool,
    ListAzureResourceGroupsTool,
    ListAzureAksClustersTool,
    ListAzureVirtualMachinesTool,
    StartAzureVirtualMachineTool,
    StopAzureVirtualMachineTool,
    GetAzureMonitorAlertsTool,
    GetAzureMonitorMetricsTool,
    GetAzureCostTool,
    ListGcpProjectsTool,
    ListGcpGkeClustersTool,
    ListGcpComputeInstancesTool,
    GetGcpComputeLogsTool,
    ListGcpCloudSqlInstancesTool,
    GetGcpCloudSqlMetricsTool,
    ListGcpCloudRunServicesTool,
    GetGcpCloudRunLogsTool,
]
