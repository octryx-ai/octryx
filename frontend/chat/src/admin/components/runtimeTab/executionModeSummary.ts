// Effective execution mode for the Execution & storage page.
// Behaviour source: backend/app/services/execution_runtime/service.py runs a
// command in Docker when the provider is `docker`; when Docker is unavailable it
// falls back to the host only if `execution_runtime_allow_host_fallback` is on,
// otherwise the command fails. `hard` sandbox mode forces the fallback off
// (services/system_config/runtime_settings.py).

export type ExecutionModeSource = {
  execution_runtime_provider?: string | null;
  execution_runtime_allow_host_fallback?: boolean | null;
  execution_runtime_sandbox_mode?: string | null;
};

export type ExecutionModeSummary = {
  target: "Host" | "Docker";
  detail: string;
};

export function executionModeSummary(
  settings: ExecutionModeSource | null | undefined,
): ExecutionModeSummary {
  const provider = String(settings?.execution_runtime_provider || "").trim().toLowerCase();
  if (provider !== "docker") {
    return {
      target: "Host",
      detail: "Commands run directly on the server, without container isolation.",
    };
  }
  const hardSandbox =
    String(settings?.execution_runtime_sandbox_mode || "").trim().toLowerCase() === "hard";
  const fallback = Boolean(settings?.execution_runtime_allow_host_fallback) && !hardSandbox;
  return {
    target: "Docker",
    detail: fallback
      ? "Commands run in a container. If Docker is unavailable, they run on the host instead."
      : "Commands run in a container. If Docker is unavailable, the command fails instead of running on the host.",
  };
}

/** Whether the unsaved drafts would change the effective mode. */
export function executionModeChanged(
  saved: ExecutionModeSource | null | undefined,
  draft: ExecutionModeSource,
): boolean {
  const before = executionModeSummary(saved);
  const after = executionModeSummary({ ...saved, ...draft });
  return before.target !== after.target || before.detail !== after.detail;
}
