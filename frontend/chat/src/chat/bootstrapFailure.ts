// The chat bootstrap failed before anything was loaded (local stack during an API restart): instead of a shell
// without a user ("No workspaces available", no Work/Operations/Admin, as if the person had lost their rights), the
// app says the server is not reachable and tries again.

/** Seconds between automatic retries while the server does not answer. */
export const BOOTSTRAP_RETRY_SECONDS = 5;

/** True when the failure is the server (not reachable, restarting, overloaded), so trying again can help. */
export function isServerUnavailable(error: unknown): boolean {
  const status = (error as { status?: unknown } | null)?.status;
  return typeof status !== "number" || status === 0 || status >= 500;
}

/** The sentence shown instead of the app. */
export function bootstrapFailureText(error: unknown): string {
  if (isServerUnavailable(error)) {
    return "Octryx is not reachable right now. The server may be restarting.";
  }
  const message = error instanceof Error ? error.message.trim() : "";
  return message ? `Octryx could not load your workspace: ${message}` : "Octryx could not load your workspace.";
}
