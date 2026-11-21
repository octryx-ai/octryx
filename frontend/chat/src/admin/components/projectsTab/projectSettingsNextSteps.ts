import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import type { ProjectSettingsTab } from "./projectSettingsSections";

// Guided next steps for the workspace overview. Every step is derived from a
// field the backend already returns (missing kinds, blockers, empty lists);
// nothing here is a generic recommendation.
export type ProjectNextStep = {
  key: string;
  title: string;
  detail: string;
  section: ProjectSettingsTab | null;
};

export function deriveProjectNextSteps(
  project: AdminProjectQuality,
  knowledgeRepositories: number | null = null,
): ProjectNextStep[] {
  const steps: ProjectNextStep[] = [];
  if (!project.is_active) {
    steps.push({
      key: "inactive",
      title: "Restore the workspace to use it",
      detail: "Inactive workspaces are hidden from chat. Restore it from the Workspaces list.",
      section: null,
    });
  }
  // Coding only works in a code repository; Knowledge repositories answer questions but are not one. No payload
  // field says whether a Workspace uses Coding, so the step says it is for Coding instead of claiming a gap.
  if ((project.code_repositories || []).length === 0) {
    steps.push({
      key: "repositories",
      title: "Add a code repository for Coding",
      detail: [
        "Coding has no repository to work in.",
        knowledgeRepositories
          ? `${repositoryCount(knowledgeRepositories, "Knowledge repository")} can be added as ${knowledgeRepositories === 1 ? "a code repository" : "code repositories"}.`
          : "",
        "Skip this if the Workspace does not use Coding.",
      ].filter(Boolean).join(" "),
      section: "repositories",
    });
  }
  // No workflow step and no design step (Design quality left the Workspace settings).
  return steps;
}

/** "1 Knowledge repository", "2 Knowledge repositories". */
export function repositoryCount(count: number, noun: string): string {
  return `${count} ${count === 1 ? noun : noun.replace(/y$/, "ies")}`;
}

// The first-run setup of a Workspace, in the order a new Workspace needs it: who may use it,
// a connected system, a synced Knowledge source, models, agents. A step is "done" only when a loaded fact says so;
// "unknown" when the fact could not be read, never guessed as done.
export type SetupStepState = "done" | "open" | "unknown";
export type WorkspaceSetupStep = { key: string; title: string; state: SetupStepState; section: ProjectSettingsTab };
export type WorkspaceSetupFacts = {
  accessEntries: number | null;
  connectors: number | null;
  syncedSources: number | null;
  allowedModels: number | null;
};

const stateOf = (count: number | null): SetupStepState => (count === null ? "unknown" : count > 0 ? "done" : "open");

export function deriveWorkspaceSetupSteps(facts: WorkspaceSetupFacts): WorkspaceSetupStep[] {
  return [
    { key: "access", title: "Add members and roles", state: stateOf(facts.accessEntries), section: "access" },
    { key: "connectors", title: "Connect a system such as Jira or Confluence", state: stateOf(facts.connectors), section: "connectors" },
    { key: "knowledge", title: "Add a Knowledge source and sync it", state: stateOf(facts.syncedSources), section: "knowledge" },
    { key: "models", title: "Allow the models this Workspace may use", state: stateOf(facts.allowedModels), section: "models" },
    { key: "agents", title: "Choose the agents and skills", state: "unknown", section: "agents" },
  ];
}
