import { useEffect, useState } from "react";

import { loadDeviceRunModels } from "./devicesApi";
import { keptModel, modelPillText, readDeviceModels, type DeviceModels } from "./deviceModelsModel";
import { setExecutionTarget, type ExecutionTarget } from "./executionTarget";
import { readableModelName } from "./modelNames";

type DeviceTarget = Extract<ExecutionTarget, { kind: "device" }>;

// The Model pill next to Profile for a device run (model picker): "device default" (what the device runs
// with when nothing is chosen) and the profile's `/model` rows for this Workspace. The choice is kept per thread
// with the rest of the target; the platform refuses a model outside the rows when the message is sent.
export function DeviceModelPill({ sessionId, projectId, target, disabled }: {
  sessionId: string | null | undefined;
  projectId: string;
  target: DeviceTarget;
  disabled: boolean;
}) {
  const [rows, setRows] = useState<DeviceModels | null>(null);

  useEffect(() => {
    if (!projectId) {
      setRows(null);
      return undefined;
    }
    let current = true;
    loadDeviceRunModels(projectId, target.profile, target.deviceId)
      .then((raw) => { if (current) setRows(readDeviceModels(raw)); })
      .catch(() => { if (current) setRows(null); });
    return () => { current = false; };
  }, [projectId, target.profile, target.deviceId]);

  useEffect(() => {
    // A model the new profile does not offer falls back to the device default instead of a refused send.
    if (!rows || rows.profile !== target.profile) return;
    const kept = keptModel(target.model, rows);
    if (kept !== (target.model ?? "")) setExecutionTarget(sessionId, { ...target, model: kept });
  }, [rows, sessionId, target]);

  return (
    <label className="composer-pill" title="Model Claude Code runs with on the device (from the profile's /model list)">
      <span className="composer-pill__display">
        <svg viewBox="0 0 24 24" aria-hidden="true" className="device-pill-icon">
          <rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" />
        </svg>
        <span>{modelPillText(target.model, rows)}</span>
      </span>
      <select aria-label="Model" value={target.model ?? ""} disabled={disabled}
        onChange={(event) => setExecutionTarget(sessionId, { ...target, model: event.target.value })}>
        <option value="">Model: device default</option>
        {(rows?.models ?? []).map((model) => (
          <option key={model.id} value={model.id} title={model.description}>{model.label}</option>
        ))}
        {target.model && !rows?.models.some((model) => model.id === target.model) ? (
          <option value={target.model}>{readableModelName(target.model)}</option>
        ) : null}
      </select>
    </label>
  );
}
