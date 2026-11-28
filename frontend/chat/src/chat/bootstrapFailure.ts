// Without this the shell looked as if the person had lost their rights (no workspaces, no Admin).

export const BOOTSTRAP_RETRY_SECONDS = 5;

export function isServerUnavailable(error: unknown): boolean {
  const status = (error as { status?: unknown } | null)?.status;
  return typeof status !== "number" || status === 0 || status >= 500;
}

export function bootstrapFailureText(error: unknown): string {
  if (isServerUnavailable(error)) {
    return "Octryx is not reachable right now. The server may be restarting.";
  }
  const message = error instanceof Error ? error.message.trim() : "";
  return message ? `Octryx could not load your workspace: ${message}` : "Octryx could not load your workspace.";
}
