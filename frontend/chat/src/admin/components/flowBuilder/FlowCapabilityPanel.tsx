import type { FlowCapability, FlowDefinitionRow } from "./flowBuilderTypes";

type FlowCapabilityPanelProps = {
  flow: FlowDefinitionRow | null;
  capability: FlowCapability | null;
  busy: boolean;
  onRefresh: () => void;
  onUnpublish: () => void;
};

function schemaFields(schema: Record<string, unknown> | undefined): string {
  const properties = schema?.properties;
  if (!properties || typeof properties !== "object") return "open object";
  const keys = Object.keys(properties as Record<string, unknown>);
  return keys.length ? keys.join(", ") : "open object";
}

function compactList(value: unknown, limit = 4): string {
  if (!Array.isArray(value)) return "";
  const items = value.map((item) => String(item || "").trim()).filter(Boolean);
  if (!items.length) return "";
  const visible = items.slice(0, limit).join(", ");
  return items.length > limit ? `${visible}, +${items.length - limit}` : visible;
}

function branchList(value: unknown): string {
  if (!Array.isArray(value)) return "";
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return "";
      const branch = item as Record<string, unknown>;
      const route = String(branch.route || "default");
      const target = String(branch.target || "").trim();
      return target ? `${route} -> ${target}` : route;
    })
    .filter(Boolean)
    .slice(0, 4)
    .join(", ");
}

export function FlowCapabilityPanel({
  flow,
  capability,
  busy,
  onRefresh,
  onUnpublish,
}: FlowCapabilityPanelProps) {
  const published = flow?.status === "published" && Boolean(flow.current_version_id);
  return (
    <section className="flow-builder__capability-panel">
      <div className="flow-builder__capability-header">
        <div>
          <span className="admin-panel__section-title">LLM capability</span>
          <p className="admin-panel__muted">
            {capability
              ? "Published workflows are available as governed runtime tools."
              : "Publish a valid flow to expose it as a governed runtime tool."}
          </p>
        </div>
        <button type="button" onClick={onRefresh} disabled={busy}>
          Refresh
        </button>
      </div>

      {capability ? (
        <div className="flow-builder__capability-card">
          <div className="flow-builder__capability-row">
            <span>Tool</span>
            <code>{capability.tool_name}</code>
          </div>
          <div className="flow-builder__capability-row">
            <span>Status</span>
            <strong>{capability.available ? "Visible" : capability.hidden_reason || "Hidden"}</strong>
          </div>
          <div className="flow-builder__capability-row">
            <span>Version</span>
            <span>v{capability.version}</span>
          </div>
          <div className="flow-builder__capability-row">
            <span>Input</span>
            <span>{schemaFields(capability.input_schema)}</span>
          </div>
          <div className="flow-builder__capability-row">
            <span>Evidence</span>
            <span>
              {Object.keys(capability.evidence_contract || {}).length ? "contracted" : "runtime trace"}
            </span>
          </div>
          {capability.process_summary?.length ? (
            <div className="flow-builder__capability-process">
              <span className="flow-builder__capability-process-title">Process visible to LLM</span>
              <ol>
                {capability.process_summary.slice(0, 8).map((step) => {
                  const label = String(step.label || step.type || "Step");
                  const type = String(step.type || "").replaceAll("_", " ");
                  const tools = compactList(step.tools);
                  const branches = branchList(step.branches);
                  return (
                    <li key={`${step.index}-${step.node_id}`}>
                      <strong>{label}</strong>
                      <span>{type}</span>
                      {tools ? <code>tools: {tools}</code> : null}
                      {branches ? <code>branches: {branches}</code> : null}
                    </li>
                  );
                })}
              </ol>
            </div>
          ) : null}
          <button
            type="button"
            className="flow-builder__danger-button"
            onClick={onUnpublish}
            disabled={busy}
          >
            Unpublish capability
          </button>
        </div>
      ) : (
        <div className="flow-builder__capability-empty">
          <span>{published ? "Capability metadata is not loaded." : "No published capability."}</span>
        </div>
      )}
    </section>
  );
}
