// A chat on the Server: its model (the Workspace's models) and how long it thinks before answering.

import { useEffect, useState } from "react";
import { loadWorkspaceChoices } from "./mobileApi";
import { readRuntimeChoices, THINKING_CHOICES, type RuntimeChoice } from "./mobileTurnOptions";

export type ServerOptions = { runtimeTargetId: string; thinkingLevel: string };

export function ServerOptionsBar({
  projectId,
  options,
  onChange,
}: {
  projectId: string;
  options: ServerOptions;
  onChange: (patch: Partial<ServerOptions>) => void;
}) {
  const [models, setModels] = useState<RuntimeChoice[]>([]);
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    loadWorkspaceChoices(projectId).then(
      (raw) => !cancelled && setModels(readRuntimeChoices(raw)),
      () => !cancelled && setModels([]),
    );
    return () => {
      cancelled = true;
    };
  }, [projectId]);
  return (
    <div className="m-options" role="group" aria-label="Options for the Server">
      <select
        aria-label="Model"
        value={options.runtimeTargetId}
        onChange={(event) => onChange({ runtimeTargetId: event.target.value })}
      >
        {models.length === 0 && <option value="">Default model</option>}
        {models.map((model) => (
          <option
            key={model.value || "automatic"}
            value={model.value}
            disabled={model.disabled}
          >
            {model.label}
          </option>
        ))}
      </select>
      <select
        aria-label="Thinking"
        value={options.thinkingLevel}
        onChange={(event) => onChange({ thinkingLevel: event.target.value })}
      >
        {THINKING_CHOICES.map((choice) => (
          <option key={choice.id} value={choice.id}>
            {choice.label}
          </option>
        ))}
      </select>
    </div>
  );
}
