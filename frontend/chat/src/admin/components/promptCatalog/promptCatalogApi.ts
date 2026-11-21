// Typed client of the prompt catalog admin API (/api/v1/prompt-catalog). Same transport and coded
// refusals as the other governed registries; every key publishes with the approval created at submit.
import { createRegistryTransport, type FetchFn } from "../governedRegistry/registryApi";
import type {
  DraftInput,
  PromptApprovalGate,
  PromptDetail,
  PromptDiff,
  PromptListResponse,
  PromptPublishResult,
  PromptVersion,
} from "./promptCatalogTypes";

export const PROMPT_CATALOG_BASE = "/api/v1/prompt-catalog";

export function createPromptCatalogApi(fetchFn?: FetchFn) {
  const { json, post } = createRegistryTransport(fetchFn);
  const version = (id: string) => `${PROMPT_CATALOG_BASE}/versions/${encodeURIComponent(id)}`;

  return {
    // Without an area: every area except the collapsed tool / MCP description areas.
    list: (area?: string) =>
      json<PromptListResponse>(area ? `${PROMPT_CATALOG_BASE}?area=${encodeURIComponent(area)}` : PROMPT_CATALOG_BASE),
    get: (key: string) => json<PromptDetail>(`${PROMPT_CATALOG_BASE}/keys/${encodeURIComponent(key)}`),
    createDraft: (key: string, input: DraftInput) =>
      post<PromptVersion>(`${PROMPT_CATALOG_BASE}/keys/${encodeURIComponent(key)}/drafts`, input),
    diff: (versionId: string) => json<PromptDiff>(`${version(versionId)}/diff`),
    submit: (versionId: string) => post<PromptVersion>(`${version(versionId)}/submit`),
    // `selfApprove`: the single-step publish the approval rule may allow (approve the own pending review).
    publish: (versionId: string, approvalId: string | null, selfApprove = false) =>
      post<PromptPublishResult>(
        `${version(versionId)}/publish`,
        selfApprove ? { self_approve: true } : { governance_approval_id: approvalId },
      ),
    // The four-eyes decision on a submitted version (same approvals API as the other governed registries).
    approve: (approvalId: string) =>
      post<unknown>(`/api/v1/approvals/${encodeURIComponent(approvalId)}/approve`, { reason: "Prompt text reviewed" }),
    reject: (approvalId: string, reason: string) =>
      post<unknown>(`/api/v1/approvals/${encodeURIComponent(approvalId)}/reject`, { reason }),
    retire: (versionId: string) => post<PromptVersion>(`${version(versionId)}/retire`),
    // Publishes the shipped text again (no review: it is the product's reviewed text).
    revert: (key: string) => post<PromptVersion>(`${PROMPT_CATALOG_BASE}/keys/${encodeURIComponent(key)}/revert`),
  };
}

export type PromptCatalogApi = ReturnType<typeof createPromptCatalogApi>;

export const promptCatalogApi = createPromptCatalogApi();
