import { useState } from "react";

import { AgentReferencesSection } from "./AgentReferencesSection";
import { AgentStepsSection } from "./AgentStepsSection";
import { AgentTestAction } from "./AgentTestAction";
import type { AgentListAgent, AgentReadiness } from "./agentListModel";
import { executionSourceLabel, revisionLabel } from "./agentWorkspaceModel";
import { toolSurfaceFromAgent, toolSurfaceLabel } from "./agentToolSurface";
import { replyFormatSummary } from "./agentReplyFormat";
import { useAgentRevision } from "./useAgentRevision";
import { ClassBadge } from "../agentsWorkflows/awBadges";
import "./agentWorkspace.css";

type AgentWorkspacePageProps = {
  agent: AgentListAgent & Record<string, any>;
  ctx: Record<string, unknown>;
  readiness: AgentReadiness;
  workspaces: { id: string; name: string; is_active?: boolean }[];
  onBack: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onLeave?: () => void;
};

type Agent = AgentWorkspacePageProps["agent"];
type Revision = ReturnType<typeof useAgentRevision>;

function AgentWorkspaceHeader({ agent, readiness, onBack, onEdit, onDelete }: Pick<AgentWorkspacePageProps,
  "agent" | "readiness" | "onBack" | "onEdit" | "onDelete">) {
  return (
  <header className="agent-workspace__header">
    <button type="button" className="admin-panel__action-btn" onClick={onBack}>← All agents</button>
    <div className="agent-workspace__title">
      <h2>{agent.name}</h2>
      <span className={`admin-panel__badge admin-panel__badge--${readiness.active ? "active" : "inactive"}`}>
        {readiness.active ? "Active" : "Inactive"}
      </span>
    </div>
    <p className="agent-workspace__facts">
      Capability ceiling <ClassBadge value={agent.capabilityCeiling || "read_only"} /> · Default workflow:{" "}
      {agent.defaultWorkflowKey || "Automatic"} · Workspace: {agent.builtinKey ? "Built-in" : readiness.workspace}
    </p>
    <div className="agent-workspace__actions">
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={onEdit}>
        Edit settings
      </button>
      {agent.builtinKey ? null : (
        <button type="button" className="admin-panel__danger-btn" onClick={onDelete}>Delete</button>
      )}
    </div>
  </header>
  );
}

type AgentRevisionSectionProps = Pick<AgentWorkspacePageProps, "agent" | "readiness" | "workspaces" | "onLeave"> & {
  revision: Revision;
  confirmPublish: boolean;
  setConfirmPublish: (confirm: boolean) => void;
};

function AgentRevisionSection({ agent, readiness, workspaces, onLeave, revision, confirmPublish, setConfirmPublish }: AgentRevisionSectionProps) {
  const draft = revision.revision?.status === "draft";
  const executes = executionSourceLabel(revision.execution, revision.revision);
  return (
  <section className="agent-workspace__section agent-workspace__status" aria-label="Revision and test">
    <div className="agent-workspace__revision">
      <strong data-testid="agent-workspace-revision">
        {revision.state === "loading" ? "Reading revision…"
          : revision.state === "error" ? "Revision state could not be read" : revisionLabel(revision.revision)}
      </strong>
      <span className="agent-workspace__hint">
        Saved changes to settings and steps are recorded as a draft revision; publishing marks the newest draft as published.
      </span>
      {draft && !confirmPublish ? (
        <button type="button" className="admin-panel__action-btn" onClick={() => setConfirmPublish(true)}>
          Publish draft…
        </button>
      ) : null}
      {draft && confirmPublish ? (
        <span className="agent-workspace__confirm">
          Publish revision {revision.revision?.revision_number}?
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={revision.publishing}
            onClick={() => { setConfirmPublish(false); void revision.publish(); }}>
            {revision.publishing ? "Publishing…" : "Publish"}
          </button>
          <button type="button" className="admin-panel__action-btn" onClick={() => setConfirmPublish(false)}>Cancel</button>
        </span>
      ) : null}
      {revision.message ? <span role="status">{revision.message}</span> : null}
    </div>
    <div className="agent-workspace__revision">
      <AgentTestAction
        agent={agent}
        active={readiness.active}
        workspaces={workspaces}
        blockedReason={executes.blocked ? executes.text : ""}
        onLeave={onLeave}
      />
      {executes.text && !executes.blocked ? (
        <span className="agent-workspace__hint" data-testid="agent-workspace-executes">{executes.text}</span>
      ) : null}
    </div>
  </section>
  );
}

function AgentOverviewSection({ agent, runtime, revision }: { agent: Agent; runtime: string; revision: Revision }) {
  // The format of this definition; published execution uses the pinned revision's format.
  const outputFormat = replyFormatSummary(agent);
  return (
  <section className="agent-workspace__section" aria-labelledby="agent-workspace-overview">
    <h3 id="agent-workspace-overview">Overview</h3>
    <p className="agent-workspace__text">{agent.description || "No description."}</p>
    <dl className="agent-workspace__grid">
      <dt>Goal</dt><dd>{agent.goal || "No goal defined"}</dd>
      <dt>Tools</dt><dd data-testid="agent-workspace-tools">{toolSurfaceLabel(toolSurfaceFromAgent(agent))}</dd>
      <dt>Output format</dt>
      <dd data-testid="agent-workspace-output-format">
        {outputFormat.label}
        {revision.execution?.mode === "published" ? " Runs use the format saved in the published revision." : ""}
        {outputFormat.fields.length ? (
          <ul className="agent-workspace__text">
            {outputFormat.fields.map((field) => (
              <li key={field.name}>
                <code>{field.name}</code> · {field.type}
                {field.required ? " · required" : " · optional"}
              </li>
            ))}
          </ul>
        ) : null}
      </dd>
      <dt>Group</dt><dd>{agent.groupName || "Ungrouped"}</dd>
      <dt>Runtime</dt><dd>{runtime}</dd>
      <dt>Thinking</dt><dd>{agent.thinkingLevel || "light"}</dd>
      <dt>Self-review</dt><dd>{agent.requireSelfReview ? "Required before finishing" : "Optional"}</dd>
      <dt>Branch prefix</dt><dd>{agent.branchPrefix || "octryx"}</dd>
    </dl>
    <details className="agent-workspace__details">
      <summary>System prompt</summary>
      <pre>{agent.systemPrompt || "No system prompt defined."}</pre>
    </details>
    <details className="agent-workspace__details">
      <summary>Output instructions (not checked)</summary>
      <pre>{agent.outputPrompt || "No output instructions defined."}</pre>
    </details>
  </section>
  );
}

// The one place to manage an agent: settings, prompts, ordered steps
// with their tool restriction, revision state and the test action, on one
// full-width page instead of a drawer plus a separate visual editor.
export function AgentWorkspacePage({
  agent, ctx, readiness, workspaces, onBack, onEdit, onDelete, onLeave,
}: AgentWorkspacePageProps) {
  const { agentBuilderMeta } = ctx as Record<string, any>;
  const revision = useAgentRevision(agent.id, JSON.stringify(agent));
  const [confirmPublish, setConfirmPublish] = useState(false);
  const runtime =
    (agentBuilderMeta?.runtime_options || []).find((option: any) => option.value === (agent.runtimeTargetId || ""))
      ?.label || "Automatic";

  return (
    <article className="agent-workspace" data-testid="agent-workspace">
      <AgentWorkspaceHeader agent={agent} readiness={readiness} onBack={onBack} onEdit={onEdit} onDelete={onDelete} />

      <AgentRevisionSection agent={agent} readiness={readiness} workspaces={workspaces} onLeave={onLeave} revision={revision}
        confirmPublish={confirmPublish} setConfirmPublish={setConfirmPublish} />

      <AgentOverviewSection agent={agent} runtime={runtime} revision={revision} />

      <AgentStepsSection agentId={agent.id} steps={agent.steps || []} ctx={ctx} />
      <AgentReferencesSection agentId={agent.id} />
    </article>
  );
}
