import { useEffect, useId, useState } from "react";

import "../agentsWorkflows/agentsWorkflows.css";
import { GovernedDrawer } from "../governedRegistry/GovernedDrawer";
import { AgentAdvancedFields } from "./AgentAdvancedFields";
import { AgentReplyFormatField } from "./AgentReplyFormatField";
import { AgentSetupField } from "./AgentSetupField";
import { formErrorAfterReplyFormatChange, replyFormatForSave } from "./agentReplyFormat";
import { type ReplyFormatState } from "./agentReplyFields";
import { AgentToolSurfaceField } from "./AgentToolSurfaceField";
import { SKILL_CATALOG_PATH } from "../skillCatalog/skillCatalogApi";
import type { SkillList, SkillRow } from "../skillCatalog/skillCatalogTypes";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type AgentFormPanelProps = {
  ctx: Record<string, unknown>;
};

// Create / edit drawer of an agent. The basics come first; a new agent starts
// with the read-only ceiling and inactive, and the expert fields
// sit in the collapsed "Advanced" section. Agents are Global: no workspace choice.
export function AgentFormPanel({ ctx }: AgentFormPanelProps) {
  const {
    agentFormError, agentFormReplyFormat, agentFormSetup,
    agentFormToolSurface, closeAgentForm, editingAgent, handleSaveAgent, readJson, setAgentFormError,
    setAgentFormReplyFormat, setAgentFormSetup, setAgentFormToolSurface, showAgentForm,
  } = ctx as Record<string, any>;
  const formId = useId();
  // Incremented when a save is blocked by the output format, so the field reveals and focuses it.
  const [replyRevealSignal, setReplyRevealSignal] = useState(0);
  const [skillOptions, setSkillOptions] = useState<SkillRow[]>([]);
  const readJsonFn = readJson as ReadJsonFn | undefined;

  useEffect(() => {
    if (!showAgentForm || !readJsonFn || skillOptions.length > 0) return;
    void readJsonFn<SkillList>(`${SKILL_CATALOG_PATH}/skills`).then(
      (list) => setSkillOptions(list.items),
      () => setSkillOptions([]),
    );
  }, [readJsonFn, showAgentForm, skillOptions.length]);

  if (!showAgentForm) return null;

  return (
    <GovernedDrawer
      variant="edit"
      eyebrow={editingAgent ? "Edit agent" : "New agent"}
      title={editingAgent ? editingAgent.name : "New agent"}
      onClose={closeAgentForm}
      footer={<AgentFormFooter ctx={ctx} formId={formId} />}
    >
      <form
        id={formId}
        className="agents-form"
        onSubmit={(e) => {
          if (!replyFormatForSave(agentFormReplyFormat).ok) setReplyRevealSignal((count) => count + 1);
          void handleSaveAgent(e);
        }}
      >
        <AgentBasicsFields ctx={ctx} />
        <AgentSetupField value={agentFormSetup} onChange={setAgentFormSetup} readJson={readJsonFn} />
        <AgentToolSurfaceField value={agentFormToolSurface} onChange={setAgentFormToolSurface}
          steps={Array.isArray(editingAgent?.steps) ? editingAgent.steps : []} />
        <AgentReplyFormatField
          value={agentFormReplyFormat}
          revealSignal={replyRevealSignal}
          onChange={(next: ReplyFormatState) => {
            setAgentFormReplyFormat(next);
            // A save message about the output format follows the fields: updated, or cleared once valid.
            const nextError = formErrorAfterReplyFormatChange(agentFormError, next);
            if (nextError !== agentFormError) setAgentFormError(nextError);
          }}
        />
        <AgentGroupFields ctx={ctx} />
        <AgentAdvancedFields ctx={ctx} skillOptions={skillOptions} />
        {agentFormError ? <div className="admin-panel__form-error">{agentFormError}</div> : null}
      </form>
    </GovernedDrawer>
  );
}

function AgentBasicsFields({ ctx }: AgentFormPanelProps) {
  const {
    agentFormDescription, agentFormGoal, agentFormName, setAgentFormDescription, setAgentFormGoal, setAgentFormName,
  } = ctx as Record<string, any>;
  return (
    <>
    <label className="agents-form__field">
      <span className="admin-panel__form-label">
        Name <span className="agents-form__required">*</span>
      </span>
      <input
        value={agentFormName}
        onChange={(e) => setAgentFormName(e.target.value)}
        required
        className="connector-field__input"
        placeholder="e.g. Knowledge builder"
      />
    </label>
    <label className="agents-form__field">
      <span className="admin-panel__form-label">Description</span>
      <input
        value={agentFormDescription}
        onChange={(e) => setAgentFormDescription(e.target.value)}
        className="connector-field__input"
        placeholder="What this agent is for, in one sentence"
      />
    </label>
    <label className="agents-form__field">
      <span className="admin-panel__form-label">Goal</span>
      <textarea
        value={agentFormGoal}
        onChange={(e) => setAgentFormGoal(e.target.value)}
        className="connector-field__input connector-field__input--textarea"
        rows={3}
      />
    </label>
    </>
  );
}

function AgentGroupFields({ ctx }: AgentFormPanelProps) {
  const { agentBuilderMeta, agentFormGroupId, setAgentFormGroupId } = ctx as Record<string, any>;
  const agentGroups = Array.isArray(agentBuilderMeta?.agent_groups)
    ? agentBuilderMeta.agent_groups
    : [];
  return (
    <>
    <label className="agents-form__field">
      <span className="admin-panel__form-label">Group</span>
      <select
        value={agentFormGroupId}
        onChange={(e) => setAgentFormGroupId(e.target.value)}
        className="connector-field__input"
      >
        <option value="">Ungrouped</option>
        {agentGroups.map((group: any) => (
          <option key={group.id} value={group.id}>
            {group.name}
          </option>
        ))}
      </select>
    </label>
    <AgentActiveSwitch ctx={ctx} />
    </>
  );
}

function AgentFormFooter({ ctx, formId }: AgentFormPanelProps & { formId: string }) {
  const { agentFormLoading, closeAgentForm, editingAgent } = ctx as Record<string, any>;
  return (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={closeAgentForm}>
        Cancel
      </button>
      <button
        type="submit"
        form={formId}
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={agentFormLoading}
      >
        {agentFormLoading ? "Saving…" : editingAgent ? "Save agent" : "Create agent"}
      </button>
    </>
  );
}

function AgentActiveSwitch({ ctx }: AgentFormPanelProps) {
  const { agentFormActive, setAgentFormActive } = ctx as Record<string, any>;
  return (
  <label className="agents-form__check">
    <input
      type="checkbox"
      checked={agentFormActive}
      onChange={(e) => setAgentFormActive(e.target.checked)}
    />
    <span>
      Agent is active
      <span className="agents-form__help">
        Inactive agents are saved but cannot be selected. Activate when the agent is ready.
      </span>
    </span>
  </label>
  );
}
