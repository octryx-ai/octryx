"""Tool classes: observability, Kubernetes, Jira and Bitbucket."""

from __future__ import annotations

from app.tools.bitbucket_impl._bitbucket_branches import CreateBitbucketBranch, ListBitbucketBranches
from app.tools.bitbucket_impl._bitbucket_delivery import AddBitbucketPullRequestComment, GetBitbucketBuildStatuses
from app.tools.bitbucket_impl._bitbucket_diff import GetBitbucketDiff
from app.tools.bitbucket_impl._bitbucket_pr_review import ListBitbucketPullRequestHeads, PostBitbucketPullRequestReview
from app.tools.bitbucket_impl._bitbucket_pull_requests import (
    CreateBitbucketPullRequest,
    GetBitbucketPullRequest,
    ListBitbucketPullRequests,
    UpdateBitbucketPullRequest,
)
from app.tools.bitbucket_impl._bitbucket_repository_base import (
    ListBitbucketDirectory,
    ListBitbucketRepositories,
    ReadBitbucketFile,
)
from app.tools.bitbucket_impl._bitbucket_repository_commits import (
    GetBitbucketCommitChanges,
    ListBitbucketCommits,
    ListRecentBitbucketCommits,
)
from app.tools.bitbucket_impl._bitbucket_sync_repo import CommitAndPushRepositoryBranch, PrepareBitbucketRepository
from app.tools.bitbucket_impl._bitbucket_users import SearchBitbucketUsers
from app.tools.grafana import (
    CreateGrafanaSnapshot,
    GetGrafanaDashboardJson,
    ListGrafanaAlerts,
    ReadGrafanaAlert,
    RenderGrafanaPanelAsImage,
)
from app.tools.jenkins_builds import ListJenkinsBuilds
from app.tools.jira_impl._jira_board_tools import ListJiraBoards, ListJiraSprints
from app.tools.jira_impl._jira_query_metadata import ListJiraIssueTypes, ListJiraPriorities
from app.tools.jira_impl._jira_query_search import SearchJiraTickets, SearchJiraUsers
from app.tools.jira_impl._jira_query_ticket_actions import (
    AddJiraComment,
    GetJiraTicket,
    ListJiraTransitions,
    TransitionJiraTicket,
)
from app.tools.jira_impl._jira_release_bundle import CreateJiraReleaseBundle
from app.tools.jira_impl._jira_sprint_issue_tools import AddIssuesToSprint, GetSprintIssues
from app.tools.jira_impl._jira_sprint_tools import CreateJiraSprint, CreateJiraSprintBundle
from app.tools.jira_impl._jira_ticket_tools import CreateJiraTicket, UpdateJiraTicket
from app.tools.jira_impl._jira_version_tools import (
    CreateJiraVersion,
    ListJiraProjects,
    ListJiraVersions,
    ReleaseJiraVersion,
)
from app.tools.kubernetes import (
    DescribeDeployment,
    DescribeNode,
    DescribePod,
    GetConfigMap,
    GetK8sDeployments,
    GetK8sEvents,
    GetPodLogs,
    GetResourceUsage,
    KubernetesTopologySnapshotTool,
    ListCronJobs,
    ListDaemonSets,
    ListEndpoints,
    ListFailedPods,
    ListHPAs,
    ListIngresses,
    ListJobs,
    ListNamespaces,
    ListNetworkPolicies,
    ListNodes,
    ListPods,
    ListPVCs,
    ListSecrets,
    ListServices,
    ListStatefulSets,
)
from app.tools.loki import QueryLoki
from app.tools.prometheus import QueryPrometheus

TOOL_CLASSES_OPS_TRACKERS = [
    ReadGrafanaAlert,
    ListGrafanaAlerts,
    RenderGrafanaPanelAsImage,
    CreateGrafanaSnapshot,
    GetGrafanaDashboardJson,
    QueryPrometheus,
    QueryLoki,
    ListJenkinsBuilds,
    KubernetesTopologySnapshotTool,
    GetK8sEvents,
    GetPodLogs,
    ListFailedPods,
    GetK8sDeployments,
    ListNamespaces,
    ListPods,
    DescribePod,
    ListServices,
    ListNodes,
    GetConfigMap,
    ListIngresses,
    GetResourceUsage,
    DescribeDeployment,
    DescribeNode,
    ListStatefulSets,
    ListDaemonSets,
    ListJobs,
    ListCronJobs,
    ListPVCs,
    ListEndpoints,
    ListNetworkPolicies,
    ListHPAs,
    ListSecrets,
    SearchJiraTickets,
    SearchJiraUsers,
    GetJiraTicket,
    ListJiraIssueTypes,
    ListJiraPriorities,
    ListJiraProjects,
    ListJiraTransitions,
    TransitionJiraTicket,
    AddJiraComment,
    CreateJiraTicket,
    UpdateJiraTicket,
    ListJiraVersions,
    CreateJiraVersion,
    ReleaseJiraVersion,
    CreateJiraReleaseBundle,
    CreateJiraSprintBundle,
    ListJiraBoards,
    ListJiraSprints,
    CreateJiraSprint,
    GetSprintIssues,
    AddIssuesToSprint,
    ListBitbucketRepositories,
    SearchBitbucketUsers,
    ListBitbucketDirectory,
    ReadBitbucketFile,
    ListBitbucketCommits,
    ListRecentBitbucketCommits,
    GetBitbucketCommitChanges,
    PrepareBitbucketRepository,
    CommitAndPushRepositoryBranch,
    ListBitbucketBranches,
    CreateBitbucketBranch,
    ListBitbucketPullRequests,
    GetBitbucketPullRequest,
    CreateBitbucketPullRequest,
    UpdateBitbucketPullRequest,
    AddBitbucketPullRequestComment,
    ListBitbucketPullRequestHeads,
    PostBitbucketPullRequestReview,
    GetBitbucketBuildStatuses,
    GetBitbucketDiff,
]
