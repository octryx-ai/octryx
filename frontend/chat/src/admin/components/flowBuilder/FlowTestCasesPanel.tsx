import { useState } from "react";
import type { FlowDefinitionNode } from "./flowBuilderTypes";
import type { FlowTestCase } from "./flowRunTypes";

type FlowTestCasesPanelProps = {
  testCases: FlowTestCase[];
  nodes: FlowDefinitionNode[];
  selectedNodeId: string | null;
  busy: boolean;
  casesDisabled?: boolean;
  onCreate: (name: string, expectedOutputJson: string) => void;
  onRun: (testCaseId: string) => void;
  onBatchRun: () => void;
  onNodeSelect: (nodeId: string | null) => void;
  onPartialRun: () => void;
};

function statusClass(status?: string | null): string {
  if (status === "passed") return "flow-builder__badge--ok";
  if (status === "completed") return "flow-builder__badge--ok";
  if (status === "failed" || status === "cancelled") return "flow-builder__badge--danger";
  if (status === "paused") return "flow-builder__badge--warning";
  return "flow-builder__badge--neutral";
}

export function FlowTestCasesPanel({
  testCases,
  nodes,
  selectedNodeId,
  busy,
  casesDisabled = false,
  onCreate,
  onRun,
  onBatchRun,
  onNodeSelect,
  onPartialRun,
}: FlowTestCasesPanelProps) {
  const [name, setName] = useState("Smoke test");
  const [expectedOutputJson, setExpectedOutputJson] = useState("{}");
  const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? null;
  return (
    <section className="flow-builder__test-panel">
      <div className="flow-builder__test-header">
        <div>
          <span className="admin-panel__section-title">Test cases</span>
          <p className="admin-panel__muted">Saved inputs, batch checks, and selected-node runs.</p>
        </div>
        <div className="flow-builder__test-create">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Test case name"
          />
          <textarea
            value={expectedOutputJson}
            onChange={(event) => setExpectedOutputJson(event.target.value)}
            placeholder='Expected output JSON, for example {"final":{"result":"ok"}}'
            rows={2}
          />
          <button
            type="button"
            onClick={() => onCreate(name, expectedOutputJson)}
            disabled={busy || casesDisabled || !name.trim()}
          >
            Save case
          </button>
          <button type="button" onClick={onBatchRun} disabled={busy || casesDisabled || !testCases.length}>
            Batch run
          </button>
          <select
            aria-label="Partial run node"
            value={selectedNodeId ?? ""}
            onChange={(event) => onNodeSelect(event.target.value || null)}
            disabled={busy || !nodes.length}
          >
            <option value="">Select node</option>
            {nodes.map((node) => (
              <option key={node.id} value={node.id}>
                {node.id} · {node.type}
              </option>
            ))}
          </select>
          <button type="button" onClick={onPartialRun} disabled={busy || !selectedNodeId}>
            Partial: {selectedNode?.id || "select node"}
          </button>
        </div>
      </div>
      {testCases.length ? (
        <div className="flow-builder__test-list">
          {testCases.map((testCase) => (
            <article key={testCase.id} className="flow-builder__test-item">
              <div>
                <strong>{testCase.name}</strong>
                <small>{Object.keys(testCase.input || {}).join(", ") || "empty input"}</small>
                {testCase.last_evaluation_summary ? (
                  <small>
                    assertions {testCase.last_evaluation_summary.passed_count}/
                    {testCase.last_evaluation_summary.total}
                  </small>
                ) : null}
              </div>
              <span className={`flow-builder__badge ${statusClass(testCase.last_evaluation_status)}`}>
                {testCase.last_evaluation_status || testCase.last_status || "not run"}
              </span>
              {testCase.changed_since_previous ? (
                <span className="flow-builder__badge flow-builder__badge--warning">changed</span>
              ) : null}
              <button type="button" onClick={() => onRun(testCase.id)} disabled={busy || casesDisabled}>
                Run case
              </button>
            </article>
          ))}
        </div>
      ) : (
        <div className="flow-builder__trace-empty">No saved test cases for this flow.</div>
      )}
    </section>
  );
}
