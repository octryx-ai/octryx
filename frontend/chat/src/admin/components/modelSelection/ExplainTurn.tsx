import { useEffect, useState } from "react";

import { explainTurn, loadExplainOptions } from "./modelSelectionApi";
import {
  TRACE_MARK,
  explainBody,
  explainFailed,
  readExplainOptions,
  readExplainResult,
} from "./modelSelectionContract";
import type { ExplainOptions, ExplainResult, ExplainTurn as Turn } from "./modelSelectionContract";
import { LoadingState } from "../../../layout/LoadingState";

const levelText = (level: string) => (level ? level.charAt(0).toUpperCase() + level.slice(1) : "no data class");

// Default & fallback → Explain a turn: the one resolver's decision for a
// Workspace and a few turn facts, read-only. Every change asks the server again; nothing is dispatched.
export function ExplainTurn() {
  const [options, setOptions] = useState<ExplainOptions | null>(null);
  const [turn, setTurn] = useState<Turn>({ workspaceId: "", personChoice: "", agentPin: "", firstFails: false });
  const [result, setResult] = useState<ExplainResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    loadExplainOptions()
      .then((payload) => {
        const read = readExplainOptions(payload);
        setOptions(read);
        setTurn((current) => ({ ...current, workspaceId: current.workspaceId || read.workspaces[0]?.id || "" }));
      })
      .catch(() => setError("The Workspaces could not be loaded."));
  }, []);

  useEffect(() => {
    if (!turn.workspaceId) return;
    let current = true;
    explainTurn(explainBody(turn))
      .then((payload) => { if (current) { setResult(readExplainResult(payload)); setError(""); } })
      .catch(() => { if (current) setError("The turn could not be explained."); });
    return () => { current = false; };
  }, [turn]);

  const update = (patch: Partial<Turn>) => setTurn((current) => ({ ...current, ...patch }));

  if (!options && !error) return <LoadingState label="Workspaces" rows={2} />;
  return (
    <div className="model-explain" data-testid="explain-turn">
      <TurnForm turn={turn} options={options} update={update} />
      <div className="admin-panel__stack">
        {error ? <p className="admin-panel__error" role="alert">{error}</p> : null}
        {result ? <ExplainOutcome result={result} /> : null}
      </div>
    </div>
  );
}

// The turn facts: the Workspace, what the person chose, the agent's pin, and whether the first model times out.
function TurnForm({ turn, options, update }: {
  turn: Turn;
  options: ExplainOptions | null;
  update: (patch: Partial<Turn>) => void;
}) {
  return (
    <div className="admin-panel__card">
      <div className="admin-panel__section-header"><span>A turn</span></div>
      <label className="admin-panel__field">
        <span>Workspace</span>
        <select value={turn.workspaceId} onChange={(event) => update({ workspaceId: event.target.value })}
          data-testid="explain-workspace">
          {options?.workspaces.map((workspace) => (
            <option key={workspace.id} value={workspace.id}>{workspace.name} ({levelText(workspace.dataClass)})</option>
          ))}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Person chose</span>
        <select value={turn.personChoice} onChange={(event) => update({ personChoice: event.target.value })}
          data-testid="explain-choice">
          <option value="">Nothing (Automatic)</option>
          {options?.models.map((model) => <option key={model.key} value={model.key}>{model.name}</option>)}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Agent pins</span>
        <select value={turn.agentPin} onChange={(event) => update({ agentPin: event.target.value })}
          data-testid="explain-agent">
          <option value="">No pin</option>
          {options?.models.map((model) => <option key={model.key} value={model.key}>{model.name}</option>)}
        </select>
      </label>
      <label className="admin-panel__checkbox">
        <input type="checkbox" checked={turn.firstFails} onChange={(event) => update({ firstFails: event.target.checked })} />
        The first model times out
      </label>
    </div>
  );
}

// The resolver's answer and the trace of how it got there.
function ExplainOutcome({ result }: { result: ExplainResult }) {
  return (
    <>
      <div className={`model-explain__result${explainFailed(result.state) ? " model-explain__result--bad" : ""}`}
        data-testid="explain-result">
        <span className="admin-panel__eyebrow">Result</span>
        <div className="model-explain__value">{result.title}</div>
        {result.note ? <span className="model-catalog__sub">{result.note}</span> : null}
      </div>
      <div className="model-explain__trace" data-testid="explain-trace">
        {result.trace.map((step, index) => (
          <div key={`${step.label}-${index}`} className="model-explain__row">
            <span className={`model-explain__mark model-explain__mark--${step.icon}`} aria-hidden="true">
              {TRACE_MARK[step.icon]}
            </span>
            <b>{step.label}</b>
            <span>{step.text}</span>
          </div>
        ))}
      </div>
    </>
  );
}
