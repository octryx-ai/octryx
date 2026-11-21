// Sentences about a Workspace connection: health, test result, global note, load failure and save outcome.
import { testResultHint } from "../connectorsTab/oidcClientCredentialsModel";
import { formatApiTime } from "../workspaceKnowledge/apiTime";
import {
  isRecord,
  type ConnectionHealth,
  type ConnectionMode,
  type WorkspaceConnection,
} from "./workspaceConnectionTypes";

export function healthText(health: ConnectionHealth | null): string {
  if (!health || health.status === "unknown") return "Not tested yet.";
  const when = health.checkedAt ? ` (${formatApiTime(health.checkedAt)})` : "";
  return health.status === "ok"
    ? `Last test: connected${when}.`
    : `Last test: failed${when}.`;
}

/** A test answer as one line: the server's fixed summary (`summary`, or `message`), never anything else. */
export function testResultText(result: unknown): { ok: boolean; text: string } {
  const said = (record: Record<string, unknown>): string | null =>
    typeof record.summary === "string" && record.summary
      ? record.summary
      : typeof record.message === "string" && record.message
        ? record.message
        : null;
  if (isRecord(result) && result.ok === true)
    return { ok: true, text: said(result) ?? "Connected." };
  // A coded failure (token endpoint, client, target system) adds its plain-words hint.
  const hint = testResultHint(result);
  const text = (isRecord(result) && said(result)) || "The test failed.";
  return { ok: false, text: hint ? `${text} ${hint}` : text };
}

/** What the "Use global connection" option adds about the global entry; "" when it can serve. */
export function globalConnectionNote(
  connection: WorkspaceConnection | null,
): string {
  if (!connection) return "";
  if (!connection.globalConfigured) return " (not set up yet, so the connector cannot run here)";
  if (!connection.globalActive) return " (Global connection is disabled, so the connector cannot use it here)";
  return "";
}

/** Why loading the connection failed, in one sentence. */
export function connectionLoadFailure(error: unknown): string {
  const status =
    isRecord(error) && typeof error.status === "number" ? error.status : null;
  const detail = error instanceof Error ? error.message : "";
  if (status === null)
    return "The server could not be reached, so this Workspace's connection was not loaded.";
  if (status === 401 || status === 403)
    return "You are not allowed to see this Workspace's connection.";
  return `This Workspace's connection could not be loaded (${status}${detail ? `: ${detail}` : ""}).`;
}

/** A load answer that is not a connection. */
export const CONNECTION_UNREADABLE = "This Workspace's connection answer could not be read.";

/** The message after a save or switch: success only when the server reports the expected mode afterwards. */
export function settledMessage(
  settled: WorkspaceConnection | null,
  expected: ConnectionMode,
  success: string,
): { ok: boolean; text: string } {
  if (!settled)
    return {
      ok: false,
      text: "The change was sent, but the server's answer could not be read, so the connection shown here may be out of date. Reload to see the current connection.",
    };
  if (settled.mode !== expected)
    return {
      ok: false,
      text:
        expected === "global"
          ? "The server still reports this Workspace's own connection, so the global connection is not in use yet."
          : "The server reports the global connection for this Workspace, so the own connection was not stored.",
    };
  return { ok: true, text: success };
}
