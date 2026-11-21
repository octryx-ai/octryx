// Start a run for a task from the phone (runs could not be started from the phone): the workflow (proposed
// from the task's kind and state), where it runs (the Server or one of the person's own Macs) and, if needed, the
// repository. The body is the web's (`startRunBody`); the platform checks the Workspace scope first and refuses a
// device that is not the person's own.

import { useEffect, useState } from "react";
import { readRuntimeTargetChoices, type RuntimeTargetChoices } from "../chat/workflowRun/runtimeTargetModel";
import { startRunBody } from "../chat/workflowRun/workflowRunRequests";
import { loadRuntimeTargets, loadStartable, startRun } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { readStartable, runRefusalText, suggestWorkflow, type Case, type StartableFlow } from "./mobileTasksModel";

export function RunStart({
  item,
  issueType,
  onStarted,
}: {
  item: Case;
  issueType: string;
  onStarted: (runId: string) => void;
}) {
  const [flows, setFlows] = useState<StartableFlow[] | null>(null);
  const [targets, setTargets] = useState<RuntimeTargetChoices>({ options: [], default: "server" });
  const [workflow, setWorkflow] = useState("");
  const [target, setTarget] = useState("");
  const [repository, setRepository] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void loadStartable(item.projectId)
      .then((raw) => alive && setFlows(readStartable(raw)))
      .catch(() => alive && setFlows([]));
    void loadRuntimeTargets(item.projectId)
      .then((raw) => {
        if (!alive) return;
        const choices = readRuntimeTargetChoices(raw);
        // A terminal run needs a terminal; on the phone only the Server and the person's Macs make sense.
        const options = choices.options.filter((option) => option.target.kind !== "terminal");
        const fallback = options.some((option) => option.key === choices.default) ? choices.default : (options[0]?.key ?? "");
        setTargets({ options, default: fallback });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [item.projectId]);

  useEffect(() => {
    if (flows && !workflow) setWorkflow(suggestWorkflow(flows, item.state, issueType, item.source));
  }, [flows, workflow, item.state, item.source, issueType]);

  const chosen = targets.options.find((option) => option.key === (target || targets.default)) ?? null;

  const start = async () => {
    if (!workflow || busy) return;
    setBusy(true);
    setError("");
    try {
      const answer = await startRun(startRunBody(workflow, item.id, repository, "", chosen?.target ?? null));
      const runId = String((answer.run as { id?: unknown } | null)?.id ?? "");
      if (runId) onStarted(runId);
    } catch (reason) {
      setError(runRefusalText((reason as MobileError).code));
    } finally {
      setBusy(false);
    }
  };

  if (flows === null) return <p className="m-muted">Loading the workflows…</p>;
  if (flows.length === 0)
    return <p className="m-muted">This Workspace has no workflow a run can start. An admin publishes one in the web.</p>;
  return (
    <section className="m-panel m-run-start">
      <span className="m-eyebrow">Start a run</span>
      <label>
        <span>Workflow</span>
        <select value={workflow} onChange={(event) => setWorkflow(event.target.value)}>
          {flows.map((flow) => (
            <option key={flow.key} value={flow.key}>
              {flow.title}
            </option>
          ))}
        </select>
      </label>
      {targets.options.length > 0 && (
        <label>
          <span>Runs on</span>
          <select value={target || targets.default} onChange={(event) => setTarget(event.target.value)}>
            {targets.options.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
                {option.online === false ? " (offline)" : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {chosen?.help && <p className="m-muted">{chosen.help}</p>}
      <details>
        <summary className="m-muted">Repository (optional)</summary>
        <input
          aria-label="Repository"
          placeholder="e.g. bitbucket:PROJECT/repo — empty: the task's default"
          value={repository}
          onChange={(event) => setRepository(event.target.value)}
        />
      </details>
      <button type="button" className="m-primary m-wide" disabled={!workflow || busy} onClick={() => void start()}>
        {busy ? "Starting…" : "Start run"}
      </button>
      {error && <p className="m-error">{error}</p>}
    </section>
  );
}
