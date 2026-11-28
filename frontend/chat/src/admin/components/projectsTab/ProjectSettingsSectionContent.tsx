import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import { CodeRepositoriesSection } from "../projectCodeSync/CodeRepositoriesSection";
import { WorkspaceDataClassificationCard } from "../dataClassification/WorkspaceDataClassificationCard";
import { agentsPolicyHref } from "../../../chat/agents/agentsFocus";
import { useAdminNavigation } from "../../adminNavigation";
import { WorkspaceModelsSection } from "../workspaceModels/WorkspaceModelsSection";
import { WorkspaceCodingSection } from "../workspaceSettings/WorkspaceCodingSection";
import { WorkspaceRulesSection } from "../workspaceSettings/WorkspaceRulesSection";
import { WorkspaceDocumentationTargetCard } from "../workspaceSettings/WorkspaceDocumentationTargetCard";
import { WorkspaceCorpIdentityCard } from "../workspaceSettings/WorkspaceCorpIdentityCard";
import { KnowledgeRepositoryPolicyPanel } from "../workspaceKnowledge/KnowledgeRepositoryPolicyPanel";
import { AdminWorkspaceCompositionSection } from "./AdminWorkspaceCompositionSection";
import { ProjectAccessSection } from "./ProjectAccessSection";
import { WorkspaceRolesSection } from "../workRoles/WorkspaceRolesSection";
import { PluginsPage } from "../plugins/PluginsPage";
import { ProjectConnectorSettingsSection } from "./ProjectConnectorSettingsSection";
import { ProjectKnowledgeLookupSection } from "./ProjectKnowledgeLookupSection";
import { ProjectObservabilitySection } from "./ProjectObservabilitySection";
import { ProjectPolicyGroup } from "./ProjectPolicyGroup";
import { ProjectQualityPoliciesSection } from "./ProjectQualityPoliciesSection";
import { ProjectResourcesSection } from "./ProjectResourcesSection";
import { WorkspaceRepositoriesSection } from "./repositories/WorkspaceRepositoriesSection";
import { PrReviewBotSection } from "./repositories/PrReviewBotSection";
import { ProjectSettingsOverview } from "./ProjectSettingsOverview";
import { ProjectSkillsSection } from "./ProjectSkillsSection";
import { ProjectVoiceSection } from "./ProjectVoiceSection";
import { ProjectWorkflowProposalSection } from "./ProjectWorkflowProposalSection";
import type { ProjectSettingsTab } from "./projectSettingsSections";
import type { WorkspaceSettingsFocus } from "./workspaceSettingsLink";

type ProjectSettingsSectionContentProps = {
  ctx: Record<string, unknown>;
  project: AdminProjectQuality;
  section: ProjectSettingsTab;
  isAdmin: boolean;
  onOpenSection: (section: ProjectSettingsTab) => void;
  // The part of the section a link asked for, shown first (Set class opens the classification card on top).
  focus?: WorkspaceSettingsFocus | null;
};

// The content of one Workspace settings section.
export function ProjectSettingsSectionContent({
  ctx, project, section, isAdmin, onOpenSection, focus = null,
}: ProjectSettingsSectionContentProps) {
  const { openAdminTab } = useAdminNavigation();
  switch (section) {
    case "access":
      return <ProjectAccessSection ctx={ctx} />;
    case "roles":
      // Work roles of this Workspace (board 8): assignments, the "Role-based tools" switch, effective permission.
      return <WorkspaceRolesSection workspaceId={project.id} workspaceName={project.name} />;
    case "plugins":
      // Workspace settings open from Admin; the server still decides (403 hides the install action).
      return <PluginsPage mode="workspace" workspace={{ id: project.id, name: project.name }} isPlatformAdmin={isAdmin} />;
    case "models":
      return <WorkspaceModelsSection projectId={project.id} />;
    case "coding":
      return <WorkspaceCodingSection projectId={project.id} isPlatformAdmin={isAdmin} onOpenModels={() => onOpenSection("models")} />;
    case "connectors":
      return <ConnectorsSection ctx={ctx} />;
    case "knowledge":
      return <KnowledgeSection ctx={ctx} project={project} isAdmin={isAdmin} />;
    case "repositories":
      return (
        <>
          <WorkspaceRepositoriesSection workspaceId={project.id} />
          {/* The PR review bot per GitHub/Bitbucket repository: one read for all rows. */}
          <PrReviewBotSection workspaceId={project.id} />
          {/* Whether members' local checkouts become a Knowledge source: a Workspace setting. */}
          <KnowledgeRepositoryPolicyPanel key={`${project.id}-repositories`} workspaceId={project.id} />
          <ProjectResourcesSection ctx={ctx} view="repositories" />
          <details className="admin-modal__stack">
            <summary className="admin-panel__hint">Advanced: local checkouts for code intelligence (no Knowledge source)</summary>
            <CodeRepositoriesSection props={ctx as never} />
          </details>
          <ProjectPolicyGroup
            title="Code quality and repository bootstrap"
            purpose="Test, lint and SAST defaults, and how repositories are created."
          >
            <ProjectQualityPoliciesSection ctx={ctx} />
          </ProjectPolicyGroup>
        </>
      );
    case "agents":
      return <AgentsSection ctx={ctx} />;
    case "rules":
      return <RulesSection project={project} isAdmin={isAdmin} onOpenSection={onOpenSection} focus={focus} openAdminTab={openAdminTab} />;
    case "observability":
      return <ProjectObservabilitySection ctx={ctx} />;
    case "voice":
      return <ProjectVoiceSection ctx={ctx} />;
    case "diagnostics":
      return <AdminWorkspaceCompositionSection ctx={ctx} view="diagnostics" onOpenSection={onOpenSection} />;
    case "overview":
    default:
      return <ProjectSettingsOverview project={project} onOpenSection={onOpenSection} />;
  }
}

type Ctx = Record<string, unknown>;

function ConnectorsSection({ ctx }: { ctx: Ctx }) {
  return (
    <>
      {/* MCP servers: Runtime's Workspace allow (WorkspaceMcpServers) inside the connector settings — one home. */}
      <ProjectConnectorSettingsSection ctx={ctx} />
    </>
  );
}

function KnowledgeSection({ ctx, project, isAdmin }: { ctx: Ctx; project: AdminProjectQuality; isAdmin: boolean }) {
  return (
    <>
      <ProjectKnowledgeLookupSection ctx={ctx} />
      {/* Where runs publish feature documentation (`section=documentation` opens it). */}
      <WorkspaceDocumentationTargetCard projectId={project.id} isAdmin={isAdmin} />
      <ProjectResourcesSection ctx={ctx} view="knowledge" />
    </>
  );
}

function AgentsSection({ ctx }: { ctx: Ctx }) {
  return (
    <>
      <AdminWorkspaceCompositionSection ctx={ctx} view="agents" />
      <ProjectSkillsSection ctx={ctx} />
      <ProjectPolicyGroup
        title="Workflow proposals"
        purpose="Whether a chat without a selected workflow gets one workflow proposal."
      >
        <ProjectWorkflowProposalSection ctx={ctx} />
      </ProjectPolicyGroup>
    </>
  );
}

function RulesSection({ project, isAdmin, onOpenSection, focus, openAdminTab }: {
  project: AdminProjectQuality;
  isAdmin: boolean;
  onOpenSection: (section: ProjectSettingsTab) => void;
  focus: WorkspaceSettingsFocus | null;
  openAdminTab: ReturnType<typeof useAdminNavigation>["openAdminTab"];
}) {
  const classificationCard = (
    <WorkspaceDataClassificationCard projectId={project.id} policyHref={agentsPolicyHref(project.id)}
      onOpenMatrix={() => openAdminTab("classificationPolicy")} />
  );
  return (
    <>
      {focus === "classification" ? classificationCard : null}
      <WorkspaceRulesSection projectId={project.id} projectName={project.name} onOpenSection={onOpenSection} />
      {focus === "classification" ? null : classificationCard}
      {/* The Corporate Identity the Spec Studio starts from. */}
      <WorkspaceCorpIdentityCard projectId={project.id} isAdmin={isAdmin} />
    </>
  );
}
