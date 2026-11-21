import { useEffect, useState } from "react";

import { loadDeviceRunModels } from "../devices/devicesApi";
import { readDeviceModels, type DeviceModels } from "../devices/deviceModelsModel";
import { engineRouteLine, keptChoice, modelListError, modelOptions, modelSource, type ModelOption } from "./runModelModel";
import type { RuntimeTarget } from "./runtimeTargetModel";
import "../work/workItemsLean.css";

export type RunModelChoices = {
  options: ModelOption[];
  // No model can be chosen here (not a device): the select is disabled and `hint` says why.
  disabled: boolean;
  // "Codex · Own subscription" below the select; null when not a device.
  line: string | null;
  hint: string | null;
};

// The models of the chosen engine and route, "Automatic" (no model sent) first. The list is the server's for the
// device's profile; Codex on the own subscription has none, so it is fixed. Keeps `value` valid when the options
// change (another device, route or engine). Shared by the web's selects and the phone's start card.
export function useRunModelChoices(projectId: string, engine: string, target: RuntimeTarget | null, value: string,
  onChange: (model: string) => void): RunModelChoices {
  const source = modelSource(engine, target);
  const sourceKey = source.kind === "server" ? `${source.profile}:${source.deviceId}` : source.kind;
  const [rows, setRows] = useState<DeviceModels | null>(null);
  const [listProblem, setListProblem] = useState<string | null>(null);

  useEffect(() => {
    setRows(null);
    setListProblem(null);
    if (source.kind !== "server" || !projectId) return;
    let cancelled = false;
    void loadDeviceRunModels(projectId, source.profile, source.deviceId)
      .then((raw) => { if (!cancelled) setRows(readDeviceModels(raw)); })
      .catch((problem) => { if (!cancelled) setListProblem(modelListError(problem)); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the source's key names it
  }, [projectId, sourceKey]);

  const options = modelOptions(source, rows);
  useEffect(() => {
    const kept = keptChoice(value, options);
    if (kept !== value) onChange(kept);
  });

  const hint = listProblem ?? (source.kind === "none" ? source.reason
    : rows?.reason ? "The Workspace allows no model on this route; the run uses the device's default." : null);
  return { options, disabled: source.kind === "none", line: engineRouteLine(engine, target), hint };
}

// "Model" in the run start box and the chat's start card.
export function RunModelSelect({ id, projectId, engine, target, value, onChange, error }: {
  id: string;
  projectId: string;
  engine: string;
  target: RuntimeTarget | null;
  value: string;
  onChange: (model: string) => void;
  error?: string | null;
}) {
  const { options, disabled, line, hint: listHint } = useRunModelChoices(projectId, engine, target, value, onChange);
  const hint = error ?? listHint;
  return (
    <div className="admin-panel__field">
      <label htmlFor={id}>Model</label>
      <select id={id} className="admin-panel__input work-run-start__target" value={value} data-testid="work-run-model"
        disabled={disabled} aria-invalid={error ? true : undefined} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option.value || "auto"} value={option.value}>{option.label}</option>)}
      </select>
      {line ? <p className="work-run-start__hint" data-testid="work-run-model-route">{line}</p> : null}
      {hint ? (
        <p className={`work-run-start__hint${error ? " work-run-start__hint--error" : ""}`} role={error ? "alert" : undefined}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
