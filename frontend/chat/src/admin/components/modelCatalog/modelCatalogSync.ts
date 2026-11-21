// Model catalog sync: reads the sync result (new, gone and unaliased models) and formats it.
import { isRecord, num, str } from "./modelCatalogReaders";

// ---- sync -----------------------------------------------------------------------------------------------------

export type SyncProposal = { providerId: string; provider: string; modelId: string; displayName: string; meta: string };
export type SyncSummary = { id: string; displayName: string; provider: string; enabled: boolean; usedBy: number; orderPosition: number | null };
export type SyncResult = { proposals: SyncProposal[]; gone: SyncSummary[]; unaliased: SyncSummary[]; failed: string[] };

function proposalMeta(item: Record<string, unknown>): string {
  const parts = [str(item.provider)];
  if (item.supports_tools === true) parts.push("tools");
  if (item.supports_vision === true) parts.push("vision");
  const context = num(item.context_length);
  if (context) parts.push(`${context >= 1000 ? `${Math.round(context / 1000)}k` : context} context`);
  return parts.filter(Boolean).join(" · ");
}

const summaries = (value: unknown): SyncSummary[] =>
  (Array.isArray(value) ? value.filter(isRecord) : []).map((item) => ({
    id: str(item.id), displayName: str(item.display_name), provider: str(item.provider), enabled: item.enabled === true,
    usedBy: num(item.used_by_workspaces) ?? 0, orderPosition: num(item.order_position),
  }));

export function readSyncResult(payload: unknown): SyncResult {
  const body = isRecord(payload) ? payload : {};
  return {
    proposals: (Array.isArray(body.new) ? body.new.filter(isRecord) : []).map((item) => ({
      providerId: str(item.provider_id), provider: str(item.provider), modelId: str(item.model_id),
      displayName: str(item.display_name) || str(item.model_id), meta: proposalMeta(item),
    })),
    gone: summaries(body.gone),
    unaliased: summaries(body.gateway_without_alias),
    failed: (Array.isArray(body.providers) ? body.providers.filter(isRecord) : [])
      .filter((item) => item.state === "failed").map((item) => str(item.provider)),
  };
}

export const proposalKey = (item: SyncProposal) => `${item.providerId}\u0000${item.modelId}`;

export function goneText(item: SyncSummary): string {
  const used = item.usedBy ? `used by ${item.usedBy} ${item.usedBy === 1 ? "Workspace" : "Workspaces"}` : "used by 0 Workspaces";
  const order = item.orderPosition ? `order #${item.orderPosition}` : "not in the platform order";
  return `${item.enabled ? "Enabled" : "Not enabled"}, ${used}, ${order}.`;
}
