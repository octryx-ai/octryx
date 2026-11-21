// The turn's options on a Mac, as in Claude Code: the model, the effort and the permission mode.
// Bypass still runs the platform's checks; the chosen options are kept per chat on this phone.

import { useEffect, useMemo, useState } from "react";
import {
  readDeviceModels,
  type DeviceModels,
} from "../chat/devices/deviceModelsModel";
import { loadDeviceModels, loadPolicy } from "./mobileApi";
import { EFFORT_CHOICES, modeChoices, readSessionModes, type TurnOptions } from "./mobileTurnOptions";

export function TurnOptionsBar({
  options,
  onChange,
  projectId,
  profile,
  deviceId,
}: {
  options: TurnOptions;
  onChange: (patch: Partial<TurnOptions>) => void;
  projectId: string;
  profile: string;
  deviceId: string;
}) {
  const [models, setModels] = useState<DeviceModels | null>(null);
  const [sessionModes, setSessionModes] = useState<string[] | null>(null);
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    loadPolicy(projectId).then(
      (raw) => !cancelled && setSessionModes(readSessionModes(raw)),
      () => !cancelled && setSessionModes(null),
    );
    return () => {
      cancelled = true;
    };
  }, [projectId]);
  const modes = useMemo(() => modeChoices(sessionModes), [sessionModes]);
  useEffect(() => {
    // A mode the person's role does not allow here falls back to the first allowed one (viewer: Plan only).
    if (modes.length && !modes.some((m) => m.id === options.permissionMode))
      onChange({ permissionMode: modes[0].id });
  }, [modes, options.permissionMode, onChange]);
  useEffect(() => {
    if (!projectId || !profile || !deviceId) return;
    let cancelled = false;
    loadDeviceModels(projectId, profile, deviceId).then(
      (raw) => !cancelled && setModels(readDeviceModels(raw)),
      () => !cancelled && setModels(null),
    );
    return () => {
      cancelled = true;
    };
  }, [projectId, profile, deviceId]);
  return (
    <div
      className="m-options"
      role="group"
      aria-label="Options for the next message"
    >
      <select
        aria-label="Model"
        value={options.model}
        onChange={(event) => onChange({ model: event.target.value })}
      >
        <option value="">Default model</option>
        {(models?.models ?? []).map((model) => (
          <option key={model.id} value={model.id}>
            {model.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Effort"
        value={options.effort}
        onChange={(event) => onChange({ effort: event.target.value })}
      >
        {EFFORT_CHOICES.map((choice) => (
          <option key={choice.id} value={choice.id}>
            {choice.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Permission mode"
        value={options.permissionMode}
        className={
          options.permissionMode === "bypassPermissions"
            ? "m-warn-select"
            : undefined
        }
        onChange={(event) => onChange({ permissionMode: event.target.value })}
      >
        {modes.map((choice) => (
          <option key={choice.id} value={choice.id}>
            {choice.label}
          </option>
        ))}
      </select>
    </div>
  );
}
