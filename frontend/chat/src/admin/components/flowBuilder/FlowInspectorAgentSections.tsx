// Flow Builder inspector: the agent step and supervisor sections (referenced agent, overrides, fallback prompt).
import type { FlowDefinitionNode } from "./flowBuilderTypes";
import { agentPageHref } from "../../agentLinks";
import type { FlowAgentOption } from "./flowPaletteModel";

export type AgentRow = FlowAgentOption;

/* ── Agent step inspector ─────────────────────────────────────────────────── */
export function AgentStepInspector({
  node,
  agents,
  onUpdate,
}: {
  node: FlowDefinitionNode;
  agents: AgentRow[];
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
}) {
  const selectedId = node.config?.agent_definition_id as string | undefined;
  const selected = agents.find((a) => a.id === selectedId);

  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__section-title">Referenced Agent</div>
      <select
        className="flow-inspector__select"
        value={selectedId ?? ""}
        onChange={(e) => {
          const agentId = e.target.value;
          onUpdate({
            config: {
              ...node.config,
              agent_definition_id: agentId || undefined,
            },
          });
        }}
      >
        <option value="">— Select an agent —</option>
        {agents.map((a) => (
          <option key={a.id} value={a.id} disabled={Boolean(a.disabledReason) && a.id !== selectedId}>
            {a.disabledReason ? `${a.name} — ${a.disabledReason}` : a.name}
          </option>
        ))}
      </select>

      {selected ? (
        <div className="flow-inspector__agent-info">
          <div className="flow-inspector__agent-name">{selected.name}</div>
          {selected.disabledReason ? <div className="flow-inspector__warning">{selected.disabledReason}</div> : null}
          {selected.goal ? (
            <div className="flow-inspector__agent-goal">{selected.goal}</div>
          ) : null}
          {selected.stepCount != null && selected.stepCount > 0 ? (
            <div className="flow-inspector__agent-steps">
              {selected.stepCount} step{selected.stepCount !== 1 ? "s" : ""}
            </div>
          ) : null}
          {/* The agent itself is managed in one place. */}
          <a className="flow-inspector__agent-link" href={agentPageHref(selected.id)} target="_blank" rel="noopener noreferrer">
            Open agent ↗
          </a>
        </div>
      ) : selectedId ? (
        <div className="flow-inspector__warning">
          Agent not found — it may have been deleted.
        </div>
      ) : (
        <div className="flow-inspector__hint">
          Select an existing agent. The flow calls this agent at runtime; agents are created and edited
          under Agents &amp; workflows → Agents.
        </div>
      )}

      <div
        className="flow-inspector__section-title"
        style={{ marginTop: "14px" }}
      >
        Runtime Overrides (optional)
      </div>
      <label className="admin-panel__field" style={{ marginTop: "6px" }}>
        <span>Thinking level</span>
        <select
          className="flow-inspector__select"
          value={(node.config?.thinking_level as string) ?? ""}
          onChange={(e) =>
            onUpdate({
              config: {
                ...node.config,
                thinking_level: e.target.value || undefined,
              },
            })
          }
        >
          <option value="">— inherit —</option>
          <option value="light">light</option>
          <option value="medium">medium</option>
          <option value="deep">deep</option>
        </select>
      </label>
    </div>
  );
}

/* ── Supervisor inspector ─────────────────────────────────────────────────── */
export function SupervisorInspector({
  node,
  agents,
  onUpdate,
}: {
  node: FlowDefinitionNode;
  agents: AgentRow[];
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
}) {
  const selectedId = node.config?.agent_definition_id as string | undefined;
  const selected = agents.find((a) => a.id === selectedId);
  const hasAgent = Boolean(selectedId);
  const hasPrompt = Boolean(node.config?.prompt);

  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__section-title">Supervisor Agent</div>
      <select
        className="flow-inspector__select"
        value={selectedId ?? ""}
        onChange={(e) => {
          const agentId = e.target.value;
          const config = { ...node.config };
          if (agentId) {
            config.agent_definition_id = agentId;
          } else {
            delete config.agent_definition_id;
          }
          onUpdate({ config });
        }}
      >
        <option value="">— Select an agent —</option>
        {agents.map((a) => (
          <option key={a.id} value={a.id} disabled={Boolean(a.disabledReason) && a.id !== selectedId}>
            {a.disabledReason ? `${a.name} — ${a.disabledReason}` : a.name}
          </option>
        ))}
      </select>

      {selected ? (
        <div className="flow-inspector__agent-info">
          <div className="flow-inspector__agent-name">{selected.name}</div>
          {selected.disabledReason ? <div className="flow-inspector__warning">{selected.disabledReason}</div> : null}
          {selected.goal ? (
            <div className="flow-inspector__agent-goal">{selected.goal}</div>
          ) : null}
        </div>
      ) : selectedId ? (
        <div className="flow-inspector__warning">
          Agent not found — it may have been deleted.
        </div>
      ) : null}

      <div
        className="flow-inspector__section-title"
        style={{ marginTop: "14px" }}
      >
        Fallback Prompt
      </div>
      <textarea
        className="flow-inspector__config"
        rows={4}
        placeholder="Supervisor prompt (used when no agent is selected)"
        value={(node.config?.prompt as string) ?? ""}
        onChange={(e) =>
          onUpdate({
            config: { ...node.config, prompt: e.target.value },
          })
        }
      />

      {!hasAgent && !hasPrompt ? (
        <div className="flow-inspector__warning" style={{ marginTop: "8px" }}>
          Supervisor requires either a selected agent or a fallback prompt.
        </div>
      ) : null}
    </div>
  );
}
