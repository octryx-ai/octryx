// Steering a run from the phone: the run's own actions (the server decides which the person has), in the web's order
// (the next action first, destructive ones last and folded away so they are not hit by mistake). An action that needs
// a value (a reason, a number, where it runs) shows its field above its button.

import { useState } from "react";
import { runActionsInOrder } from "../chat/workflowRun/runCardModel";
import { actionReady, runActionRequest } from "../chat/workflowRun/workflowRunRequests";
import { type RunAction, type RunActionValue, type WorkflowRun } from "../chat/workflowRun/workflowRunTypes";
import { postRunAction } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { runRefusalText } from "./mobileTasksModel";

// Actions that open a new terminal session or need the web's richer forms stay there.
const WEB_ONLY = new Set(["resume_in_new_session"]);

const isDanger = (action: RunAction) => action.tone === "danger" || action.key === "stop" || action.key === "abort";

export function RunActions({
  run,
  hide = [],
  onDone,
}: {
  run: WorkflowRun;
  // Actions another card already offers (the decision card's confirm and change).
  hide?: string[];
  onDone: (run: WorkflowRun) => void;
}) {
  const actions = runActionsInOrder(run).filter((action) => !WEB_ONLY.has(action.key) && !hide.includes(action.key));
  const main = actions.filter((action) => !isDanger(action));
  const danger = actions.filter(isDanger);
  if (!actions.length) return null;
  return (
    <section className="m-panel m-run-actions" aria-labelledby="m-steer">
      <h2 id="m-steer" className="m-section">
        Steer the run
      </h2>
      {main.map((action, index) => (
        <RunActionForm key={action.key} run={run} action={action} primary={index === 0 && !hide.length} onDone={onDone} />
      ))}
      {danger.length > 0 && (
        <details className="m-fold">
          <summary>Stop or abort the run</summary>
          {danger.map((action) => (
            <RunActionForm key={action.key} run={run} action={action} onDone={onDone} />
          ))}
        </details>
      )}
    </section>
  );
}

export function RunActionForm({
  run,
  action,
  primary = false,
  label,
  value: given,
  onDone,
}: {
  run: WorkflowRun;
  action: RunAction;
  primary?: boolean;
  // The decision card names its buttons by what happens next and composes the text itself.
  label?: string;
  value?: RunActionValue;
  onDone: (run: WorkflowRun) => void;
}) {
  const input = given === undefined ? (action.input ?? null) : null;
  const [value, setValue] = useState<RunActionValue>(input?.default ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const chosen = given === undefined ? value : given;
  const send = async () => {
    setBusy(true);
    setError("");
    try {
      const { path, body } = runActionRequest(run, action, chosen);
      const answer = await postRunAction(path, body);
      onDone(answer.run as WorkflowRun);
    } catch (reason) {
      setError(runRefusalText((reason as MobileError).code));
    } finally {
      setBusy(false);
    }
  };
  const ready = given === undefined ? actionReady(action, value) : Boolean(String(given ?? "").trim()) || !action.input;
  const tone = isDanger(action) ? "m-danger" : primary ? "m-primary" : "m-secondary";
  return (
    <div className="m-action">
      {input?.kind === "text" && (
        <label className="m-field">
          <span>{input.label}</span>
          <textarea rows={2} value={String(value ?? "")} onChange={(event) => setValue(event.target.value)} />
        </label>
      )}
      {input?.kind === "number" && (
        <label className="m-field">
          <span>{input.label}</span>
          <input
            type="number"
            inputMode="numeric"
            min={input.min}
            max={input.max}
            value={Number(value ?? input.default)}
            onChange={(event) => setValue(Number(event.target.value))}
          />
        </label>
      )}
      {input?.kind === "runtime_target" && (
        <label className="m-field">
          <span>{input.label}</span>
          <select value={String(value ?? "")} onChange={(event) => setValue(event.target.value)}>
            {input.options.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <button type="button" className={`${tone} m-full`} disabled={busy || !ready} onClick={() => void send()}>
        {busy ? "Sending…" : (label ?? action.label)}
      </button>
      {error && (
        <p className="m-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
