import { readJson } from "../../utils/adminPanelHelpers";
import type { CommandSafety } from "../commandSafety/commandSafetyModel";
import { readCommandSafety } from "../commandSafety/commandSafetyModel";
import type { ClassifiedWorkspace } from "../dataClassification/ClassificationWorkspacesTab";
import type { ClassificationPolicy } from "../dataClassification/classificationPolicyModel";
import { readClassificationPolicy } from "../dataClassification/classificationPolicyModel";
import { loadClassificationPolicy, loadClassificationWorkspaces } from "../dataClassification/dataClassificationApi";
import type { ToolApprovals } from "../toolApprovals/toolApprovalsModel";
import { readToolApprovals } from "../toolApprovals/toolApprovalsModel";
import type { Coding, McpServer, ToolVisibility } from "./workspaceSettingsModel";
import { readCoding, readMcpServers, readToolVisibility } from "./workspaceSettingsModel";

// Everything Workspace → Rules shows, each read from the page that declares it. A part the caller may not read
// (platform-admin pages for a Workspace admin) is null; the row then only links to its page.
export type WorkspaceRules = {
  classification: ClassificationPolicy | null;
  classified: ClassifiedWorkspace | null;
  approvals: ToolApprovals | null;
  commandSafety: CommandSafety | null;
  mcp: McpServer[] | null;
  coding: Coding | null;
  tools: ToolVisibility | null;
};

async function settle<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch {
    return null;
  }
}

export async function loadWorkspaceRules(projectId: string): Promise<WorkspaceRules> {
  const base = `/api/v1/admin/workspaces/${encodeURIComponent(projectId)}`;
  const [classification, classified, approvals, commandSafety, mcp, coding, tools] = await Promise.all([
    settle(async () => readClassificationPolicy(await loadClassificationPolicy(), true)),
    settle(async () => {
      const answer = await loadClassificationWorkspaces();
      const rows = answer && typeof answer === "object" ? (answer as { workspaces?: unknown }).workspaces : null;
      return Array.isArray(rows) ? (rows.find((row) => row?.id === projectId) as ClassifiedWorkspace | undefined) ?? null : null;
    }),
    settle(async () => readToolApprovals(await readJson<unknown>("/api/v1/admin/tool-approvals"))),
    settle(async () => readCommandSafety(await readJson<unknown>("/api/v1/admin/command-safety"))),
    settle(async () => readMcpServers(await readJson<unknown>(`${base}/mcp-servers`))),
    settle(async () => readCoding(await readJson<unknown>(`${base}/coding`))),
    settle(async () => readToolVisibility(await readJson<unknown>(`${base}/tools`))),
  ]);
  return { classification, classified, approvals, commandSafety, mcp, coding, tools };
}
