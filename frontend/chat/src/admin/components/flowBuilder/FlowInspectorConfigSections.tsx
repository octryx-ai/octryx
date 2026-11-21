// Flow Builder inspector: tool, trigger and generic JSON config sections of a selected step.
import type { FlowDefinitionNode } from "./flowBuilderTypes";

export type ToolRow = {
  name: string;
  description?: string;
  is_core?: boolean;
};

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function parseMaybe(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return undefined;
  }
}

/* ── Tool step inspector ───────────────────────────────────────────────────── */
export function ToolStepInspector({
  node,
  tools,
  onUpdate,
}: {
  node: FlowDefinitionNode;
  tools: ToolRow[];
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
}) {
  const selectedTools = (node.config?.allowed_tools as string[]) ?? [];

  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__section-title">Allowed Tools</div>
      <div className="flow-inspector__tool-list">
        {tools.length === 0 ? (
          <p className="admin-panel__muted" style={{ fontSize: "var(--ds-text-xs)" }}>
            No tools loaded. Add tools in the Tool Catalog tab.
          </p>
        ) : (
          tools.map((t) => {
            const isSelected = selectedTools.includes(t.name);
            return (
              <label key={t.name} className="flow-inspector__tool-item">
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...selectedTools, t.name]
                      : selectedTools.filter((n) => n !== t.name);
                    onUpdate({
                      config: { ...node.config, allowed_tools: next },
                    });
                  }}
                />
                <span className="flow-inspector__tool-name">
                  {t.name}
                  {t.is_core ? (
                    <span className="flow-inspector__tool-core"> core</span>
                  ) : null}
                </span>
                {t.description ? (
                  <span className="flow-inspector__tool-desc">
                    {t.description}
                  </span>
                ) : null}
              </label>
            );
          })
        )}
      </div>
      <div className="flow-inspector__hint" style={{ marginTop: "8px" }}>
        {selectedTools.length > 0
          ? `${selectedTools.length} tool${selectedTools.length !== 1 ? "s" : ""} selected`
          : "No tools selected — all allowed."}
      </div>
    </div>
  );
}

/* ── Trigger inspector ─────────────────────────────────────────────────────── */
export function TriggerInspector({
  node,
  onUpdate,
}: {
  node: FlowDefinitionNode;
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
}) {
  const triggerType = (node.config?.trigger_type as string) ?? "manual";

  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__section-title">Trigger Type</div>
      <select
        className="flow-inspector__select"
        value={triggerType}
        onChange={(e) =>
          onUpdate({
            config: { ...node.config, trigger_type: e.target.value },
          })
        }
      >
        <option value="manual">Manual (user-initiated)</option>
        <option value="scheduler">Scheduled (cron)</option>
        <option value="webhook">Webhook</option>
      </select>

      {triggerType === "scheduler" ? (
        <label className="admin-panel__field" style={{ marginTop: "10px" }}>
          <span>Cron expression</span>
          <input
            type="text"
            className="flow-inspector__input"
            placeholder="0 9 * * 1-5"
            value={(node.config?.cron_expression as string) ?? ""}
            onChange={(e) =>
              onUpdate({
                config: { ...node.config, cron_expression: e.target.value },
              })
            }
          />
        </label>
      ) : null}

      {triggerType === "webhook" ? (
        <label className="admin-panel__field" style={{ marginTop: "10px" }}>
          <span>Webhook path</span>
          <input
            type="text"
            className="flow-inspector__input"
            placeholder="/api/v1/webhooks/my-trigger"
            value={(node.config?.webhook_path as string) ?? ""}
            onChange={(e) =>
              onUpdate({
                config: { ...node.config, webhook_path: e.target.value },
              })
            }
          />
        </label>
      ) : null}
    </div>
  );
}

/* ── Generic config inspector ─────────────────────────────────────────────── */
export function GenericConfigInspector({
  node,
  onUpdate,
}: {
  node: FlowDefinitionNode;
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
}) {
  const configJson = node.config ? prettyJson(node.config) : "{}";

  function handleConfigChange(raw: string) {
    const parsed = parseMaybe(raw);
    if (parsed !== undefined) {
      onUpdate({ config: parsed as Record<string, unknown> });
    }
  }

  return (
    <div className="flow-inspector__section">
      <div className="flow-inspector__section-title">Config (JSON)</div>
      <textarea
        className="flow-inspector__config"
        rows={8}
        value={configJson}
        onChange={(e) => handleConfigChange(e.target.value)}
      />
    </div>
  );
}

export function RawConfigInspector({
  node,
  onUpdate,
}: {
  node: FlowDefinitionNode;
  onUpdate: (patch: Partial<FlowDefinitionNode>) => void;
}) {
  return (
    <details className="flow-inspector__raw-config">
      <summary>Raw config JSON</summary>
      <GenericConfigInspector node={node} onUpdate={onUpdate} />
    </details>
  );
}
