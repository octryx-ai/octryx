import { useEffect, useState, type ReactNode } from "react";

import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import { readJson } from "../../utils/adminPanelHelpers";
import { loadWorkspaceClassification } from "../dataClassification/dataClassificationApi";
import { readWorkspaceClassification } from "../dataClassification/dataClassificationModel";
import { readWorkspaceModels } from "../workspaceModels/workspaceModelsModel";
import { readMcpServers } from "../workspaceSettings/workspaceSettingsModel";
import { connectorsApi } from "../workspaceKnowledge/connectorsApi";
import { StatusLabel } from "../../../layout/StatusLabel";
import "./workspaceList.css";
import { deriveProjectNextSteps, deriveWorkspaceSetupSteps, type SetupStepState } from "./projectSettingsNextSteps";
import { loadRepositorySources } from "./repositories/workspaceRepositoriesApi";
import { projectSettingsSectionLabel, type ProjectSettingsTab } from "./projectSettingsSections";
import { SEAT_CARD_LABEL } from "../../../chat/agents/agentsFocus";
import { workspaceSectionHref } from "./workspaceSettingsLink";

type Glance = {
  level: string | null; models: string[] | null; servers: string[] | null; knowledgeRepositories: number | null;
  accessEntries: number | null; connectors: number | null; syncedSources: number | null;
};

const count = (value: unknown) => (Array.isArray(value) ? value.length : 0);

async function loadGlance(projectId: string): Promise<Glance> {
  const base = `/api/v1/admin/workspaces/${encodeURIComponent(projectId)}`;
  const [classification, models, mcp, sources, access, connectors] = await Promise.allSettled([
    loadWorkspaceClassification(projectId), readJson<unknown>(`${base}/models`), readJson<unknown>(`${base}/mcp-servers`),
    loadRepositorySources(projectId),
    readJson<Record<string, unknown>>(`/admin/chat/api/panel/projects/${encodeURIComponent(projectId)}/access`),
    connectorsApi.list(projectId),
  ]);
  const accessView = access.status === "fulfilled" ? access.value : null;
  const connectorList = connectors.status === "fulfilled" ? connectors.value.connectors ?? [] : null;
  const read = classification.status === "fulfilled" ? readWorkspaceClassification(classification.value) : null;
  const level = read?.effective ? read.levels.find((item) => item.value === read.effective)?.label ?? read.effective : null;
  const view = models.status === "fulfilled" ? readWorkspaceModels(models.value) : null;
  const servers = mcp.status === "fulfilled" ? readMcpServers(mcp.value) : null;
  return {
    level,
    models: view ? view.models.filter((row) => row.allowed).map((row) => row.label) : null,
    servers: servers ? servers.filter((server) => server.allowed).map((server) => server.name) : null,
    knowledgeRepositories: sources.status === "fulfilled" ? sources.value.length : null,
    accessEntries: accessView
      ? count(accessView.assignments) + count(accessView.group_assignments) + count(accessView.role_assignments) : null,
    connectors: connectorList ? connectorList.length : null,
    syncedSources: connectorList ? connectorList.filter((item) => item.last_run?.state === "completed").length : null,
  };
}

// Every step that is not proven done looks the same: an open circle, counted as open.
const SETUP_MARK: Record<SetupStepState, string> = { done: "✓", open: "○", unknown: "○" };
const SETUP_STATE_LABEL: Record<SetupStepState, string> = { done: "Done", open: "Open", unknown: "Open" };

const list = (values: string[] | null, none: string) => (values === null ? "–" : values.length ? values.join(", ") : none);

function Pair({ label, children }: { label: string; children: ReactNode }) {
  return <dl className="work-detail__kv"><dt>{label}</dt><dd>{children}</dd></dl>;
}

// Workspace → Overview: the Workspace's level, models, MCP servers and
// repositories, each line linking to the section that declares it, plus the open setup steps from the payload.
// Code repositories (what Coding works in) and Knowledge repositories (git sources synced into Knowledge) are
// counted separately, so a Workspace with only Knowledge repositories is not reported as having none.
export function ProjectSettingsOverview({ project, onOpenSection }: {
  project: AdminProjectQuality;
  onOpenSection: (section: ProjectSettingsTab) => void;
}) {
  const [glance, setGlance] = useState<Glance | null>(null);
  useEffect(() => {
    let current = true;
    setGlance(null);
    void loadGlance(project.id).then((next) => { if (current) setGlance(next); });
    return () => { current = false; };
  }, [project.id]);

  const repositories = project.code_repositories || [];
  const indexed = repositories.filter((item) => item.last_index_status === "ready").length;
  const steps = deriveProjectNextSteps(project, glance?.knowledgeRepositories ?? null);
  const setup = glance ? deriveWorkspaceSetupSteps({
    accessEntries: glance.accessEntries, connectors: glance.connectors, syncedSources: glance.syncedSources,
    allowedModels: glance.models ? glance.models.length : null,
  }) : null;
  const openSetup = setup ? setup.filter((step) => step.state !== "done").length : 0;
  const link = (section: ProjectSettingsTab, children: ReactNode) => (
    <button type="button" className="sk-link" onClick={() => onOpenSection(section)}>{children}</button>
  );
  const knowledgeRepositories = glance ? glance.knowledgeRepositories ?? "–" : "…";

  return (
    <div className="sk-wsec workspace-overview" data-testid="workspace-overview">
      <section className="workspace-overview__section" aria-labelledby="workspace-glance-title">
        <h3 id="workspace-glance-title" className="workspace-overview__title">At a glance</h3>
        <div className="work-detail__kv-grid" data-testid="workspace-glance">
          <Pair label="Status">{project.is_active ? "Active" : "Inactive"}{project.is_system ? " · protected system Workspace" : ""}</Pair>
          <Pair label="Description">{project.description || "–"}</Pair>
          <Pair label="Level">{glance ? link("rules", glance.level ?? "No level") : "…"}</Pair>
          <Pair label="Models">{glance ? link("models", list(glance.models, "None allowed")) : "…"}</Pair>
          <Pair label="MCP servers">{glance ? link("connectors", list(glance.servers, "None")) : "…"}</Pair>
          <Pair label="Repositories">
            {link("repositories", `Code repositories: ${repositories.length ? `${repositories.length} (${indexed} indexed)` : "none"}`)}
            {" · "}Knowledge repositories: {knowledgeRepositories}
          </Pair>
          <Pair label="Seats">
            <a className="sk-link" href={workspaceSectionHref(project.id, "classification")} data-testid="workspace-seat-card-link">{SEAT_CARD_LABEL}</a>
          </Pair>
          <Pair label="Rules">{link("rules", "Everything that limits this Workspace")}</Pair>
        </div>
      </section>
      {setup ? (
        <section className="workspace-overview__section" aria-label="Set up this Workspace" data-testid="workspace-setup">
          <div className="workspace-overview__head">
            <h3 className="workspace-overview__title">Set up this Workspace</h3>
            <StatusLabel label={openSetup ? `${openSetup} open` : "Done"} tone="neutral" />
          </div>
          <ol className="workspace-setup">
            {setup.map((step) => (
              <li key={step.key} className={`workspace-setup__step workspace-setup__step--${step.state}`} data-state={step.state}>
                <span className="workspace-setup__mark" aria-label={SETUP_STATE_LABEL[step.state]}>{SETUP_MARK[step.state]}</span>
                {link(step.section, step.title)}
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      {steps.length ? (
        <section className="workspace-overview__section" aria-label="Also">
          <h3 className="workspace-overview__title">Also</h3>
          <ul className="sk-checks">
            {steps.map((step) => (
              <li key={step.key} className="is-info">
                <span>
                  <b>{step.title}.</b> {step.detail}{" "}
                  {step.section ? link(step.section, `Open ${projectSettingsSectionLabel(step.section).toLowerCase()}`) : null}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
