import { useRef, useState } from "react";
import { readJson } from "../chatApiClient";
import { RunPayload } from "../workflowRun/RunPayload";
import { actionReady, runActionRequest, runViewPath } from "../workflowRun/workflowRunRequests";
import { payloadView } from "../workflowRun/workflowRunPayloadView";
import { type RunAction, type RunActionValue, type WorkflowRun } from "../workflowRun/workflowRunTypes";

export function WorkflowDecisionButton({ runId }: { runId: string }) {
  return <DecisionPanel key={runId} runId={runId} />;
}

function DecisionPanel({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false);
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [inputs, setInputs] = useState<Record<string, number | string>>({});
  const pending = useRef(false);

  async function load() {
    setRun(null);
    setInputs({});
    try {
      const payload = await readJson<{ run: WorkflowRun }>(runViewPath(runId));
      if (payload.run?.id === runId) setRun(payload.run);
      else setProblem("The current decision is unavailable.");
    } catch {
      setProblem("The current decision is unavailable or you no longer have access.");
    }
  }

  async function show() {
    if (pending.current) return;
    pending.current = true;
    setOpen(true);
    setBusy(true);
    setProblem("");
    try { await load(); } finally { pending.current = false; setBusy(false); }
  }

  function valueOf(action: RunAction): RunActionValue {
    return action.input ? inputs[action.key] ?? action.input.default : null;
  }

  async function choose(action: RunAction) {
    if (!run || pending.current || !run.actions.includes(action) || !actionReady(action, valueOf(action))) return;
    pending.current = true;
    setBusy(true);
    setProblem("");
    const request = runActionRequest(run, action, valueOf(action));
    try {
      const payload = await readJson<{ run: WorkflowRun }>(request.path, {
        method: "POST", body: JSON.stringify(request.body),
      });
      setRun(payload.run?.id === runId ? payload.run : null);
      setInputs({});
    } catch {
      // Never repeat a refused action: discard the stale card and read the viewer's current permissions.
      setProblem("The action was refused. Check the current decision before acting again.");
      await load();
    } finally { pending.current = false; setBusy(false); }
  }

  function change(key: string, value: number | string) {
    setInputs(current => ({ ...current, [key]: value }));
  }

  return <span>
    <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => void show()}>
      {busy ? "Loading…" : "Open decision"}
    </button>
    {open ? <section aria-label="Workflow decision" aria-live="polite">
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => { setOpen(false); setRun(null); }}>Close decision</button>
      {run ? <>
        <h3>{run.title}</h3>
        {run.waiting?.question ? <p>{run.waiting.question}</p> : null}
        <RunPayload view={payloadView(run.waiting ?? null)} />
        {run.waiting?.payload_hash ? <p>Payload hash: <code>{run.waiting.payload_hash}</code></p> : null}
        <div role="group" aria-label="Decision actions">
          {run.actions.filter(action => !action.input || ["text", "number", "runtime_target"].includes(action.input.kind))
            .map(action => <span key={action.key}>
              {action.input?.kind === "text" ? <label className="admin-panel__field">{action.input.label}
                <input type="text" required={action.input.required} maxLength={action.input.name === "branch" ? 200 : 500}
                  value={String(valueOf(action) ?? "")} disabled={busy}
                  onChange={event => change(action.key, event.target.value)} />
              </label> : null}
              {action.input?.kind === "number" ? <label className="admin-panel__field">{action.input.label}
                <input type="number" min={action.input.min} max={action.input.max} value={Number(valueOf(action))}
                  disabled={busy} onChange={event => change(action.key, Number(event.target.value))} />
              </label> : null}
              {action.input?.kind === "runtime_target" ? <label className="admin-panel__field">{action.input.label}
                <select value={String(valueOf(action))} disabled={busy} onChange={event => change(action.key, event.target.value)}>
                  {action.input.options.map(option => <option key={option.key} value={option.key}>{option.label}</option>)}
                </select>
              </label> : null}
              <button type="button" className="admin-panel__action-btn" disabled={busy || !actionReady(action, valueOf(action))}
                onClick={() => void choose(action)}>{action.label}</button>
            </span>)}
        </div>
      </> : null}
      {problem ? <p role="status">{problem}</p> : null}
    </section> : null}
  </span>;
}
