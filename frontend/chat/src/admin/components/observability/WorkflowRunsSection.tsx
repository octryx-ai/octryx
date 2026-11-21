import { useCallback, useEffect, useState } from "react";

import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { chatSessionHref } from "../../../chat/workflowRun/workflowRunModel";
import { RUN_STATUS_FILTERS, runStatusLabel, runStatusTone } from "../../../chat/workflowRun/workflowRunStatus";
import { runsListPath, runViewPath } from "../../../chat/workflowRun/workflowRunRequests";
import { type RunAction, type RunRow } from "../../../chat/workflowRun/workflowRunTypes";
import { Badge, Segmented } from "./obUi";
import { formatTime, readErrorMessage } from "./obFormat";

// The approver's place for a run's four-eyes approval: the run names the actions this viewer may take.
function RunApprovalCell({
  runId,
  readJson,
  onDecided,
}: {
  runId: string;
  readJson: ReadJsonFn;
  onDecided: () => void;
}) {
  const [actions, setActions] = useState<RunAction[] | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const open = async () => {
    try {
      const view = await readJson<{ run: { actions: RunAction[] } }>(
        runViewPath(runId),
      );
      const decisions = view.run.actions.filter(
        (action) => action.key === "approve" || action.key === "reject",
      );
      setActions(decisions);
      if (!decisions.length)
        setNote("Another admin decides (approval rule: four-eyes).");
    } catch (error) {
      setNote(readErrorMessage(error, "The run could not be loaded."));
    }
  };
  const decide = async (action: RunAction) => {
    try {
      await readJson(`${runViewPath(runId)}/actions`, {
        method: "POST",
        body: JSON.stringify({ action: action.key }),
      });
      onDecided();
    } catch (error) {
      setNote(readErrorMessage(error, "The decision could not be recorded."));
    }
  };

  if (actions === null) {
    return (
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={() => void open()}
      >
        Decide
      </button>
    );
  }
  return <ApprovalActions actions={actions} note={note} onDecide={(action) => void decide(action)} />;
}

// The approve and reject buttons this viewer may use, and why there are none.
function ApprovalActions({
  actions,
  note,
  onDecide,
}: {
  actions: RunAction[];
  note: string | null;
  onDecide: (action: RunAction) => void;
}) {
  return (
    <span className="ob-section__actions">
      {actions.map((action) => (
        <button
          key={action.key}
          type="button"
          className="admin-panel__action-btn"
          onClick={() => onDecide(action)}
        >
          {action.label}
        </button>
      ))}
      {note ? <span className="ob-muted">{note}</span> : null}
    </span>
  );
}

// Observability → Runs → Workflow runs: runs of workflows anchored on Work
// items, filtered by state; "Needs a decision" lists paused and waiting runs first. Each opens the run's chat,
// where its card decides; nothing is decided here.
export function WorkflowRunsSection({ readJson }: { readJson: ReadJsonFn }) {
  const [status, setStatus] = useState("attention");
  const [rows, setRows] = useState<RunRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows((await readJson<{ runs: RunRow[] }>(runsListPath(status))).runs);
      setError(null);
    } catch (loadError) {
      setError(
        readErrorMessage(loadError, "Workflow runs could not be loaded."),
      );
    }
  }, [readJson, status]);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section
      className="ob-section"
      aria-label="Workflow runs"
      data-testid="workflow-runs"
    >
      <div className="ob-toolbar">
        <strong>Workflow runs</strong>
        <Segmented
          label="Workflow run state"
          options={RUN_STATUS_FILTERS}
          value={status}
          onChange={setStatus}
        />
      </div>
      {error ? (
        <div className="ob-warn" role="alert">
          {error}
        </div>
      ) : null}
      {rows && rows.length ? (
        <RunsTable rows={rows} readJson={readJson} onDecided={() => void load()} />
      ) : rows ? (
        <p className="ob-muted">No workflow run in this state.</p>
      ) : null}
    </section>
  );
}

// One row per run: its workflow, state, node, ticket and update time, and its decision or chat link.
function RunsTable({
  rows,
  readJson,
  onDecided,
}: {
  rows: RunRow[];
  readJson: ReadJsonFn;
  onDecided: () => void;
}) {
  return (
    <table className="admin-panel__table ob-cards">
      <thead>
        <tr>
          <th>Workflow</th>
          <th>State</th>
          <th>Node</th>
          <th>Ticket</th>
          <th>Updated</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td data-label="Workflow">{row.title}</td>
            <td data-label="State">
              <Badge tone={runStatusTone(row.status)}>
                {runStatusLabel(row)}
              </Badge>
            </td>
            <td data-label="Node">{row.current_node_id ?? ""}</td>
            <td data-label="Ticket">{row.ticket_key ?? ""}</td>
            <td data-label="Updated">
              {row.updated_at ? formatTime(row.updated_at) : ""}
            </td>
            <td>
              {row.waiting_kind === "awaiting_approval" ? (
                <RunApprovalCell
                  runId={row.id}
                  readJson={readJson}
                  onDecided={onDecided}
                />
              ) : row.session_id ? (
                <a href={chatSessionHref(row.session_id)}>Open the run</a>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
