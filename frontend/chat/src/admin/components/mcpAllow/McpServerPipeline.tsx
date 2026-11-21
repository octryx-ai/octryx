import { StatusLabel } from "../../../layout/StatusLabel";
import { inUse, pipeline } from "./mcpAllowContract";
import type { ServerStatus } from "./mcpAllowContract";
import "./mcpAllow.css";

// registered → connected → allowed in n Workspaces → tools visible to agents. Shown in the
// MCP server's side panel; the footer holds the panel's primary action, so "Allow in Workspaces" stays a plain button.
export function McpServerPipeline({ status, onAllow }: { status: ServerStatus | undefined; onAllow: () => void }) {
  const steps = pipeline(status);
  return (
    <section className="mcp-allow__section" data-testid="mcp-pipeline">
      <div className="mcp-allow__head">
        <StatusLabel label={inUse(status) ? "In use" : "Not usable yet"} tone={inUse(status) ? "neutral" : "attention"} />
        <button type="button" className="admin-panel__action-btn" onClick={onAllow} data-testid="mcp-allow-open">
          Allow in Workspaces
        </button>
      </div>
      <div className="mcp-allow__pipeline">
        {steps.map((step, index) => (
          <span key={step.label}>
            <span className={step.done ? "mcp-allow__step--done" : "mcp-allow__step--open"}>
              {step.done ? "✓" : "○"} {step.label}
            </span>
            {index < steps.length - 1 ? <span className="mcp-allow__arrow"> → </span> : null}
          </span>
        ))}
      </div>
    </section>
  );
}
