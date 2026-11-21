// How the /admin/tools config form reads the answer of its save or test post once the post goes through fetch
// (toolsConfigGuard.ts). The routes answer 303 (save), an HTML page (test), 409 secret_rebind_required, or an error.

export type ToolsConfigOutcome = "refused" | "navigate" | "replace_page" | "failed";

export function classifyToolsConfigResponse(status: number, redirected: boolean, contentType: string | null): ToolsConfigOutcome {
  if (status === 409) return "refused";
  if (status >= 200 && status < 300 && redirected) return "navigate";
  if (status >= 200 && status < 300 && (contentType ?? "").includes("text/html")) return "replace_page";
  return "failed";
}

// A failed post's text: the server's string detail when it sent one, else the status. Object details are not echoed.
export function failureText(status: number, payload: unknown): string {
  const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : null;
  if (typeof detail === "string" && detail.trim()) return `The request failed: ${detail.trim()}`;
  return `The request failed (${status}).`;
}
