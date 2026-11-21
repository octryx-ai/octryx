// Parts of the guided "Run an agent" fields: workspace, agent, execution, capability and instruction.
import { agentPageHref } from "../../agentLinks";
import type { AdminNavigation } from "../../adminNavigation";
import type { PanelAgentRow } from "../taskTypes";
import { CAPABILITY_CHOICES, type GuidedConfigView } from "./actionGuidedConfig";
import { type ExecutionView } from "./actionGuidedExecution";
import { type WorkspaceOption } from "./actionGuidedPath";

export type ActionGuidedFieldsProps = {
  isNew: boolean;
  workspaces: WorkspaceOption[];
  workspaceId: string;
  /** Edit only: the stored workspace, shown read-only. */
  workspaceLabel: string;
  onWorkspace: (workspaceId: string) => void;
  agents: PanelAgentRow[];
  agentId: string;
  agent: PanelAgentRow | null;
  agentAvailable: boolean;
  onAgent: (agentId: string) => void;
  modeLabel: string;
  execution: ExecutionView;
  onRetryExecution: () => void;
  /** Set when the published content's instructions are checked by the runtime, not here. */
  instructionNote: string | null;
  config: GuidedConfigView;
  onPrompt: (prompt: string) => void;
  onCapability: (capability: string) => void;
  /** The current execution setting in plain language (a new Action always runs its agent directly). */
  bindingText: string;
  /** Only for an existing Action without an explicit binding: the explicit, unchecked-by-default conversion. */
  offerConversion: boolean;
  convertBinding: boolean;
  onConvertBinding: (convert: boolean) => void;
};

type PartProps = { props: ActionGuidedFieldsProps };
type NavigatingPartProps = PartProps & { openAdminTab: AdminNavigation["openAdminTab"] };

export function GuidedWorkspaceField({ props, openAdminTab }: NavigatingPartProps) {
  const { isNew, workspaces, workspaceId, workspaceLabel, onWorkspace } = props;
  return (
    <div className="task-form__field task-form__field--full">
      <label
        className="admin-panel__form-label"
        htmlFor="action-guided-workspace"
      >
        Workspace *
      </label>
      {isNew ? (
        workspaces.length ? (
          <select
            id="action-guided-workspace"
            className="connector-field__input"
            value={workspaceId}
            onChange={(event) => onWorkspace(event.target.value)}
          >
            <option value="">Choose a workspace…</option>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
        ) : (
          <div className="admin-form-help">
            You have no active workspace to run an action in.{" "}
            <button
              type="button"
              className="admin-panel__action-btn"
              onClick={() => openAdminTab("projects")}
            >
              Open workspaces
            </button>
          </div>
        )
      ) : (
        <div id="action-guided-workspace" className="action-guided__readonly">
          {workspaceLabel}{" "}
          <span className="admin-panel__cell--muted">
            (an action keeps its workspace)
          </span>
        </div>
      )}
    </div>
  );
}

export function GuidedAgentField({ props, openAdminTab }: NavigatingPartProps) {
  const { workspaceId, agents, agentId, agent, agentAvailable, onAgent } = props;
  return (
    <div className="task-form__field task-form__field--full">
      <label
        className="admin-panel__form-label"
        htmlFor="action-guided-agent"
      >
        Agent *
      </label>
      {workspaceId && !agents.length && !agent ? (
        <div className="admin-form-help">
          No active agent is available in this workspace.{" "}
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => openAdminTab("agents")}
          >
            Open agents
          </button>
        </div>
      ) : (
        <select
          id="action-guided-agent"
          className="connector-field__input"
          value={agentId}
          disabled={!workspaceId}
          onChange={(event) => onAgent(event.target.value)}
        >
          <option value="">
            {workspaceId ? "Choose an agent…" : "Choose a workspace first"}
          </option>
          {agent && !agentAvailable ? (
            <option value={agent.id}>{agent.name} (not available)</option>
          ) : null}
          {agentId && !agent ? (
            <option value={agentId}>Saved agent (not found)</option>
          ) : null}
          {agents.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
              {option.projectId ? "" : " (global)"}
            </option>
          ))}
        </select>
      )}
      <GuidedAgentDetails props={props} />
    </div>
  );
}

function GuidedAgentDetails({ props }: PartProps) {
  const { agent, execution, onRetryExecution, modeLabel } = props;
  return agent ? (
    <div className="action-guided__agent">
      <a
        href={agentPageHref(agent.id)}
        target="_blank"
        rel="noopener noreferrer"
      >
        Open agent ↗
      </a>
      <div
        className="admin-form-help"
        data-testid="action-guided-execution"
      >
        {execution.text}
        {execution.retry ? (
          <>
            {" "}
            <button
              type="button"
              className="admin-panel__action-btn"
              onClick={onRetryExecution}
            >
              Retry
            </button>
          </>
        ) : null}
      </div>
      <div className="admin-form-help" data-testid="action-guided-mode">
        Run mode:{" "}
        <strong>{modeLabel || "none set on the agent"}</strong>, taken
        from the agent. When published revisions run, the mode saved in
        that revision applies.
      </div>
    </div>
  ) : null;
}

export function GuidedBindingField({ props }: PartProps) {
  const { bindingText, offerConversion, convertBinding, onConvertBinding } = props;
  return (
    <div className="task-form__field task-form__field--full">
      <div className="admin-panel__form-label">How it runs</div>
      <div className="admin-form-help" data-testid="action-guided-binding">
        {bindingText}
      </div>
      {offerConversion ? (
        <label className="action-guided__choice">
          <input
            type="checkbox"
            id="action-guided-binding-convert"
            checked={convertBinding}
            onChange={(event) => onConvertBinding(event.target.checked)}
          />
          <span>
            <strong>Run the chosen agent directly from now on</strong> —
            saving replaces this action&apos;s existing execution setup with a
            direct run of the chosen agent. The server checks the agent first
            and changes nothing if it is refused. Earlier runs stay as they
            are.
          </span>
        </label>
      ) : null}
    </div>
  );
}

export function GuidedCapabilityField({ props, configLocked }: PartProps & { configLocked: boolean }) {
  const { config, onCapability } = props;
  return (
    <fieldset className="action-guided__capability" disabled={configLocked}>
      <legend className="admin-panel__form-label">What runs may do</legend>
      {config.capabilityInvalid ? (
        <div className="admin-panel__form-error">
          The saved capability_class {config.capabilityInvalid} is not valid.
          Choose one below or fix it under Advanced.
        </div>
      ) : null}
      {CAPABILITY_CHOICES.map((choice) => (
        <label key={choice.value} className="action-guided__choice">
          <input
            type="radio"
            name="action-guided-capability"
            value={choice.value}
            checked={
              !config.capabilityInvalid && config.capability === choice.value
            }
            onChange={() => onCapability(choice.value)}
          />
          <span>
            <strong>{choice.label}</strong> — {choice.detail}
          </span>
        </label>
      ))}
    </fieldset>
  );
}

export function GuidedPromptField({ props, configLocked }: PartProps & { configLocked: boolean }) {
  const { config, onPrompt, instructionNote } = props;
  return (
    <>
      <div className="task-form__field task-form__field--full">
        <label
          className="admin-panel__form-label"
          htmlFor="action-guided-prompt"
        >
          Instruction for each run{" "}
          <span className="admin-panel__cell--muted">(optional)</span>
        </label>
        <textarea
          id="action-guided-prompt"
          className="connector-field__input connector-field__input--textarea"
          rows={3}
          value={config.prompt}
          disabled={configLocked || config.promptInvalid}
          onChange={(event) => onPrompt(event.target.value)}
          placeholder="e.g. Summarise yesterday's failed deployments."
        />
        <div className="admin-form-help">
          Sent as the request of every run. When empty, the agent's own
          execution prompt is sent.
        </div>
        {instructionNote && !config.prompt.trim() ? (
          <div
            className="admin-form-help"
            data-testid="action-guided-instruction-note"
          >
            {instructionNote}
          </div>
        ) : null}
      </div>
      {config.error ? (
        <div className="admin-panel__form-error">
          {config.error} Fix it under Advanced to use these fields.
        </div>
      ) : null}
    </>
  );
}
