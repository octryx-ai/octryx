// Mirrors the backend: without Docker the host fallback runs only when allowed, and hard sandbox mode forbids it.

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

export function executionModeChanged(
  saved: ExecutionModeSource | null | undefined,
  draft: ExecutionModeSource,
): boolean {
  const before = executionModeSummary(saved);
  const after = executionModeSummary({ ...saved, ...draft });
  return before.target !== after.target || before.detail !== after.detail;
}
