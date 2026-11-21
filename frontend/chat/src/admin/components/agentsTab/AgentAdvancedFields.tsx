import { useState } from "react";

import type { SkillRow } from "../skillCatalog/skillCatalogTypes";
import { AgentSkillPreferencesField } from "./AgentSkillPreferencesField";

type AgentAdvancedFieldsProps = {
  ctx: Record<string, unknown>;
  skillOptions: SkillRow[];
};

type AnyCtx = Record<string, any>;

// Thinking level, runtime, branch prefix and the self-review switch.
function AgentRuntimeFields({ ctx, thinkingLevels, runtimeOptions }: { ctx: AnyCtx; thinkingLevels: string[]; runtimeOptions: any[] }) {
  const {
    agentFormBranchPrefix, agentFormRequireSelfReview, agentFormRuntimeId, agentFormThinking, setAgentFormBranchPrefix,
    setAgentFormRequireSelfReview, setAgentFormRuntimeId, setAgentFormThinking,
  } = ctx;
  return (
    <>
      <label className="agents-form__field">
        <span className="admin-panel__form-label">Thinking</span>
        <select
          value={agentFormThinking}
          onChange={(e) => setAgentFormThinking(e.target.value)}
          className="connector-field__input"
        >
          {thinkingLevels.map((level: string) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </label>
      <label className="agents-form__field">
        <span className="admin-panel__form-label">Runtime</span>
        <select
          value={agentFormRuntimeId}
          onChange={(e) => setAgentFormRuntimeId(e.target.value)}
          className="connector-field__input"
        >
          {runtimeOptions.map((runtime: any) => (
            <option key={runtime.value || "auto"} value={runtime.value}>
              {runtime.label}
            </option>
          ))}
        </select>
      </label>
      <label className="agents-form__field">
        <span className="admin-panel__form-label">Branch prefix</span>
        <input
          value={agentFormBranchPrefix}
          onChange={(e) => setAgentFormBranchPrefix(e.target.value)}
          className="connector-field__input"
          placeholder="octryx"
        />
        <span className="agents-form__help">Prefix of the Git branches this agent creates.</span>
      </label>
      <label className="agents-form__check">
        <input
          type="checkbox"
          checked={agentFormRequireSelfReview}
          onChange={(e) => setAgentFormRequireSelfReview(e.target.checked)}
        />
        <span>Require a self-review before the agent finishes</span>
      </label>
    </>
  );
}

function AgentPromptFields({ ctx }: { ctx: AnyCtx }) {
  const { agentFormOutputPrompt, agentFormSystemPrompt, setAgentFormOutputPrompt, setAgentFormSystemPrompt } = ctx;
  return (
    <>
      <label className="agents-form__field">
        <span className="admin-panel__form-label">System prompt</span>
        <textarea
          value={agentFormSystemPrompt}
          onChange={(e) => setAgentFormSystemPrompt(e.target.value)}
          className="connector-field__input connector-field__input--textarea"
          rows={4}
        />
      </label>
      <label className="agents-form__field">
        <span className="admin-panel__form-label">Output instructions</span>
        <textarea
          value={agentFormOutputPrompt}
          onChange={(e) => setAgentFormOutputPrompt(e.target.value)}
          className="connector-field__input connector-field__input--textarea"
          rows={4}
        />
        <span className="agents-form__help">
          Free-text guidance on how answers should look. It is not checked; for a checked reply choose Structured data
          under Output format.
        </span>
      </label>
    </>
  );
}

// Expert settings of an agent, collapsed by default. It opens on its own only
// when an existing agent already uses one of them, so nothing is hidden.
export function AgentAdvancedFields({ ctx, skillOptions }: AgentAdvancedFieldsProps) {
  const {
    agentBuilderMeta,
    agentFormBlockedSkillIds,
    agentFormOutputPrompt,
    agentFormPreferredSkillIds,
    agentFormRequireSelfReview,
    agentFormRuntimeId,
    agentFormSystemPrompt,
    setAgentFormBlockedSkillIds,
    setAgentFormPreferredSkillIds,
  } = ctx as Record<string, any>;
  const thinkingLevels = Array.isArray(agentBuilderMeta?.thinking_levels)
    ? agentBuilderMeta.thinking_levels
    : ["off", "light", "deep"];
  const runtimeOptions = Array.isArray(agentBuilderMeta?.runtime_options)
    ? agentBuilderMeta.runtime_options
    : [];
  const [open] = useState(
    Boolean(
      agentFormSystemPrompt ||
        agentFormOutputPrompt ||
        agentFormRequireSelfReview ||
        agentFormRuntimeId ||
        agentFormPreferredSkillIds?.length ||
        agentFormBlockedSkillIds?.length,
    ),
  );

  return (
    <details className="agents-form__advanced" open={open || undefined}>
      <summary>Advanced</summary>
      <div className="agents-form__advanced-body">
        <AgentRuntimeFields ctx={ctx} thinkingLevels={thinkingLevels} runtimeOptions={runtimeOptions} />
        <AgentPromptFields ctx={ctx} />
        <AgentSkillPreferencesField
          skills={skillOptions}
          preferredSkillIds={agentFormPreferredSkillIds || []}
          blockedSkillIds={agentFormBlockedSkillIds || []}
          setPreferredSkillIds={setAgentFormPreferredSkillIds}
          setBlockedSkillIds={setAgentFormBlockedSkillIds}
        />
      </div>
    </details>
  );
}
