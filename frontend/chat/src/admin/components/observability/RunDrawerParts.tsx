import { Badge } from "./obUi";
import { formatDuration, formatMoney } from "./obFormat";
import { outcomeLabel, outcomeTone, type RunDetail, type RunRow } from "./runsModel";
import type { RunContent } from "./useRunDetail";

function stepLabel(step: RunDetail["steps"][number]): string {
  if (step.gate) return `${step.gate.label || step.gate.gate}: ${step.gate.status}${step.gate.reason ? ` (${step.gate.reason})` : ""}`;
  const tokens = step.tokens_in || step.tokens_out ? ` · ${step.tokens_in} in / ${step.tokens_out} out` : "";
  return `Model call · ${step.model || step.provider || "unknown model"}${tokens}`;
}

function offset(start: string | null, time: string | null): string {
  if (!start || !time) return "–";
  return formatDuration(Math.max(0, new Date(time).getTime() - new Date(start).getTime()));
}

// Workspace, user, outcome and cost, from the list row when there is one.
export function RunFacts({ row, detail }: { row?: RunRow; detail: RunDetail | null }) {
  const outcome = row?.outcome ?? detail?.outcome ?? null;
  return (
    <div className="ob-kv">
      <div><b>Workspace</b>{row?.workspace_name ?? detail?.workspace_name ?? "No Workspace"}</div>
      <div><b>User</b>{row?.user_name ?? detail?.user_name ?? "–"}</div>
      <div><b>Outcome</b><Badge tone={outcomeTone(outcome)}>{outcomeLabel(outcome)}</Badge></div>
      <div>
        <b>Cost</b>
        {(row?.cost_state ?? detail?.cost.state) === "unpriced" ? <Badge tone="attention">! unpriced</Badge>
          : (row?.cost_state ?? detail?.cost.state) === "not_billed" ? "seat · not billed"
            : formatMoney(row?.cost ?? detail?.cost.total ?? null)}
      </div>
    </div>
  );
}

// The model calls, gates and tool calls with their offset from the start.
export function RunSteps({ detail }: { detail: RunDetail }) {
  const start = detail?.started_at ?? detail?.steps[0]?.time ?? null;
  return (
    <section className="work-detail__section">
      <h3>Steps</h3>
      <div className="ob-steps">
        {detail.steps.map((step, index) => (
          <div className="ob-step" key={`${step.time}-${index}`}>
            <span className="ob-mono">{offset(start, step.time)}</span>
            <span>{stepLabel(step)}</span>
            <Badge tone={outcomeTone(step.outcome)}>{outcomeLabel(step.outcome)}</Badge>
          </div>
        ))}
        {detail.tools.map((tool, index) => (
          <div className="ob-step" key={`tool-${index}`}>
            <span className="ob-mono">{offset(start, tool.time)}</span>
            <span>Tool · {tool.tool}{tool.duration_ms !== null ? ` · ${formatDuration(tool.duration_ms)}` : ""}</span>
            <Badge tone={tool.status === "success" ? "active" : "danger"}>{tool.status === "success" ? "ok" : tool.status.replace(/_/g, " ")}</Badge>
          </div>
        ))}
      </div>
      {detail.steps_truncated ? <span className="ob-muted">Only the first 200 steps are shown.</span> : null}
    </section>
  );
}

// The gates that stopped this run, and the cost per model.
export function RunDecisionsAndCost({ detail }: { detail: RunDetail }) {
  const gates = (detail?.steps ?? []).filter((step) => step.gate);
  return (
    <>
      <section className="work-detail__section">
        <h3>Decisions in this run</h3>
        {gates.length ? gates.map((step, index) => (
          <div className="ob-row" key={`gate-${index}`}>
            <Badge tone="danger">{step.gate?.status.replace(/_/g, " ")}</Badge>
            <span>{step.gate?.label}{step.gate?.reason ? `: ${step.gate.reason}` : ""}</span>
          </div>
        )) : <span className="ob-muted">No gate stopped this run.</span>}
      </section>
      {detail.cost.by_model.length ? (
        <section className="work-detail__section">
          <h3>Cost</h3>
          {detail.cost.by_model.map((item) => (
            <div className="ob-between" key={`${item.model}-${item.state}`}>
              <span>{item.model || "unknown model"} · {item.calls} call{item.calls === 1 ? "" : "s"}</span>
              {item.state === "unpriced" ? <Badge tone="attention">! no price</Badge>
                : item.state === "not_billed" ? <span className="ob-muted">not billed</span> : <span>{formatMoney(item.cost)}</span>}
            </div>
          ))}
        </section>
      ) : null}
    </>
  );
}

// The effective setup (when asked for) and the content, hidden until the audited read.
export function RunSetupAndContent({ detail, showSetup, content, onShowContent }: {
  detail: RunDetail;
  showSetup: boolean;
  content: RunContent | null;
  onShowContent: () => void;
}) {
  return (
    <>
      {showSetup && detail.effective_setup ? (
        <section className="work-detail__section">
          <h3>Effective setup</h3>
          <span className="ob-muted">The execution profile this run was frozen under (bounded, secrets redacted).</span>
          <pre className="ob-diff">{JSON.stringify(detail.effective_setup, null, 2)}</pre>
        </section>
      ) : null}
      <section className="work-detail__section">
        <h3>Content</h3>
        {content ? (
          <pre className="ob-diff">{JSON.stringify(content, null, 2)}</pre>
        ) : (
          <>
            <span className="ob-muted">Hidden by default. Secrets are redacted; viewing the content is written to the audit log.</span>
            <div>
              <button type="button" className="admin-panel__action-btn" onClick={onShowContent}>
                Show content (audited)
              </button>
            </div>
          </>
        )}
      </section>
    </>
  );
}
