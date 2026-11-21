import { useMemo } from "react";
import type { FlowNodeRunTrace, FlowRunTracePayload } from "./flowRunTypes";
import { flowRunResultView } from "./flowRunResult";
import { RawResult, RunDiagnostics, RunNotices, RunOutcome, RunResultContent } from "./FlowRunResultParts";
import { flowRunStepCounts } from "./flowRunStepCounts";
import { approvalIdFromNodeRun, asRecord, compactValue, evidenceLabel, planStepsFromRunPlan, statusClass } from "./flowTraceFormat";
import { DecisionTraceSummary, ToolEvidenceSummary, TraceBlock } from "./FlowTraceSummaries";

type FlowTracePanelProps = {
  trace: FlowRunTracePayload | null;
  selectedNodeRunId: string | null;
  running: boolean;
  onRefresh: () => void;
  onRecoverInterrupted: () => void;
  onResume: (decision: "approve" | "reject", approvalId: string | null) => void;
  onCancel: () => void;
  onSelectNodeRun: (nodeRunId: string) => void;
};

type TraceDecisionActionsProps = {
  running: boolean;
  approvalId: string | null;
  onResume: FlowTracePanelProps["onResume"];
  onCancel: () => void;
};

function TraceDecisionActions({ running, approvalId, onResume, onCancel }: TraceDecisionActionsProps) {
  return (
    <div className="flow-builder__trace-decision-actions">
      <button type="button" onClick={() => onResume("approve", approvalId)} disabled={running || !approvalId}>
        Approve & resume
      </button>
      <button type="button" onClick={() => onResume("reject", approvalId)} disabled={running || !approvalId}>
        Reject
      </button>
      <button type="button" onClick={onCancel} disabled={running}>Cancel run</button>
    </div>
  );
}

function TracePlan({ runPlan, planSteps }: { runPlan: Record<string, unknown>; planSteps: Record<string, unknown>[] }) {
  return (
    <div className="flow-builder__trace-plan">
      <div className="flow-builder__trace-detail-head">
        <div>
          <strong>Plan state</strong>
          <span>{compactValue(runPlan.status)}</span>
        </div>
        <span>{planSteps.length} steps</span>
      </div>
      <div className="flow-builder__trace-plan-list">
        {planSteps.map((step) => {
          const status = compactValue(step.status);
          return (
            <div key={compactValue(step.id ?? step.node_id)} className="flow-builder__trace-plan-step">
              <span className={`flow-builder__badge ${statusClass(status === "done" ? "completed" : status)}`}>{status}</span>
              <strong>{compactValue(step.label ?? step.node_id)}</strong>
              {step.reason ? <small>{compactValue(step.reason)}</small> : null}
              {step.required_action ? <small>{compactValue(step.required_action)}</small> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

type TraceStepRowsProps = {
  nodeRuns: FlowNodeRunTrace[];
  selectedNodeRun: FlowNodeRunTrace | null;
  onSelectNodeRun: (nodeRunId: string) => void;
};

function TraceStepRows({ nodeRuns, selectedNodeRun, onSelectNodeRun }: TraceStepRowsProps) {
  return (
    <div className="flow-builder__trace-table" role="list" aria-label="Step runs, including skipped steps and retries">
      {nodeRuns.map((nodeRun) => (
        <button
          key={nodeRun.id}
          type="button"
          role="listitem"
          aria-current={nodeRun.id === selectedNodeRun?.id ? "true" : undefined}
          className={nodeRun.id === selectedNodeRun?.id ? "flow-builder__trace-row flow-builder__trace-row--active" : "flow-builder__trace-row"}
          onClick={() => onSelectNodeRun(nodeRun.id)}
        >
          <span>
            <strong>{nodeRun.node_id}</strong>
            <small>{nodeRun.node_type}{Number(nodeRun.attempt || 1) > 1 ? ` · attempt ${nodeRun.attempt}` : ""}</small>
          </span>
          <span className={`flow-builder__badge ${statusClass(nodeRun.status)}`}>{nodeRun.status}</span>
          <span>{evidenceLabel(nodeRun.evidence_summary)}</span>
          <span>{nodeRun.artifact_refs?.length ?? 0} artifacts</span>
          <span>{nodeRun.duration_ms ?? "—"} ms</span>
        </button>
      ))}
    </div>
  );
}

function TraceStepDetail({ nodeRun }: { nodeRun: FlowNodeRunTrace }) {
  return (
    <div className="flow-builder__trace-detail">
      <div className="flow-builder__trace-detail-head">
        <div>
          <strong>{nodeRun.node_id}</strong>
          <span>{nodeRun.node_type}</span>
        </div>
        <span className={`flow-builder__badge ${statusClass(nodeRun.status)}`}>{nodeRun.status}</span>
      </div>
      {nodeRun.error ? <div className="flow-builder__trace-error">{nodeRun.error}</div> : null}
      <ToolEvidenceSummary output={nodeRun.output} />
      <DecisionTraceSummary value={nodeRun.decision_trace} />
      <TraceBlock title="Input" value={nodeRun.input} />
      <TraceBlock title="Output" value={nodeRun.output} />
      <TraceBlock title="Decision trace" value={nodeRun.decision_trace} />
      <TraceBlock title="Evidence" value={nodeRun.evidence_summary} />
      <TraceBlock title="Artifacts" value={nodeRun.artifact_refs} />
      <TraceBlock title="Trace refs" value={nodeRun.trace_refs} />
      <TraceBlock title="Usage" value={nodeRun.token_usage} />
    </div>
  );
}

type TraceStepDetailsProps = TraceStepRowsProps & {
  stepCounts: ReturnType<typeof flowRunStepCounts>;
  runPlan: Record<string, unknown>;
  planSteps: Record<string, unknown>[];
};

function TraceStepDetails({ stepCounts, runPlan, planSteps, nodeRuns, selectedNodeRun, onSelectNodeRun }: TraceStepDetailsProps) {
  return (
    <details className="flow-run-panel__section">
      <summary>
        Step details ({stepCounts.steps} step{stepCounts.steps === 1 ? "" : "s"}
        {stepCounts.attemptsNote ? `, ${stepCounts.attempts} attempts` : ""})
      </summary>
      {planSteps.length ? <TracePlan runPlan={runPlan} planSteps={planSteps} /> : null}
      <div className="flow-builder__trace-grid">
        <TraceStepRows nodeRuns={nodeRuns} selectedNodeRun={selectedNodeRun} onSelectNodeRun={onSelectNodeRun} />
        {selectedNodeRun ? <TraceStepDetail nodeRun={selectedNodeRun} /> : null}
      </div>
    </details>
  );
}

// The result of the latest run, result first: the outcome in plain words, failures and
// review/approval notices, the terminal output; raw result, step details and diagnostics
// (lease, ids, times, acceptance and validation facts) are collapsed secondary sections.
export function FlowTracePanel({
  trace,
  selectedNodeRunId,
  running,
  onRefresh,
  onRecoverInterrupted,
  onResume,
  onCancel,
  onSelectNodeRun,
}: FlowTracePanelProps) {
  const selectedNodeRun = useMemo<FlowNodeRunTrace | null>(() => {
    if (!trace?.node_runs?.length) return null;
    return trace.node_runs.find((nodeRun) => nodeRun.id === selectedNodeRunId) ?? trace.node_runs[0] ?? null;
  }, [trace, selectedNodeRunId]);
  const pausedNodeRun = useMemo(() => trace?.node_runs?.find((nodeRun) => nodeRun.status === "paused") ?? null, [trace?.node_runs]);
  if (!trace) {
    return (
      <section className="flow-builder__trace-panel" aria-label="Run result">
        <div className="flow-builder__trace-empty">No run yet. Run this revision to see its result and the status of every step.</div>
      </section>
    );
  }
  const approvalId = approvalIdFromNodeRun(pausedNodeRun);
  const hasRecoverableAttempt =
    ["running", "failed"].includes(trace.run.status) &&
    trace.node_runs.some((nodeRun) => ["running", "failed"].includes(nodeRun.status));
  const runPlan = asRecord(trace.run.plan);
  const planSteps = planStepsFromRunPlan(runPlan);
  const view = flowRunResultView(trace);
  // Steps by their latest attempt: "3 completed · 1 skipped", not "4 steps executed".
  const stepCounts = flowRunStepCounts(trace.node_runs);

  return (
    <section className="flow-builder__trace-panel" aria-label="Run result">
      <div className="flow-builder__trace-summary">
        <RunOutcome view={view} steps={stepCounts} />
        <span className="flow-builder__trace-buttons">
          <button type="button" onClick={onRefresh} disabled={running}>Refresh</button>
          {hasRecoverableAttempt ? (
            <button type="button" onClick={onRecoverInterrupted} disabled={running}>Recover run</button>
          ) : null}
        </span>
      </div>
      <RunNotices notices={view.notices} />
      {trace.run.status === "paused" && pausedNodeRun ? (
        <TraceDecisionActions running={running} approvalId={approvalId} onResume={onResume} onCancel={onCancel} />
      ) : null}
      <RunResultContent result={view.result} />
      <RawResult raw={view.raw} />

      {stepCounts.attempts ? (
        <TraceStepDetails stepCounts={stepCounts} runPlan={runPlan} planSteps={planSteps} nodeRuns={trace.node_runs}
          selectedNodeRun={selectedNodeRun} onSelectNodeRun={onSelectNodeRun} />
      ) : null}
      <RunDiagnostics rows={view.diagnostics} rawFacts={view.rawFacts} />
    </section>
  );
}
