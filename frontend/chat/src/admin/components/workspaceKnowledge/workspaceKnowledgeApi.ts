// Typed client of the governed Workspace Knowledge API (/api/v1/workspaces/{id}/knowledge).
// Every call is Workspace-scoped by the path; the server authorizes it and renders fixed states.
import type {
  BindingsOverview,
  CatalogEntry,
  ChangesResult,
  EvidenceWindow,
  GraphStatus,
  KnowledgePackage,
  SearchResult,
  SourceDetail,
  SourceListing,
  SourceRequest,
  UploadResult,
  WebSearchOverview,
} from "./workspaceKnowledgeTypes";
import { knowledgeBase, request, webSearchBase } from "./workspaceKnowledgeRequest";

/** The server's window ({passages: [{text, is_hit}]}) as the found passage with the ones before and after it. */
export function readEvidenceWindow(payload: unknown): EvidenceWindow | null {
  const passages = (payload as { passages?: unknown } | null)?.passages;
  if (!Array.isArray(passages)) return null;
  const items = passages.filter((item): item is { text: string; is_hit?: unknown } =>
    !!item && typeof (item as { text?: unknown }).text === "string");
  const hit = items.findIndex((item) => item.is_hit === true);
  if (hit < 0) return null;
  return {
    passage: items[hit].text,
    before: items.slice(0, hit).map((item) => item.text),
    after: items.slice(hit + 1).map((item) => item.text),
  };
}

export const webSearchApi = {
  overview: (id: string) => request<WebSearchOverview>(`${webSearchBase(id)}/sources`),
  put: (id: string, body: SourceRequest) =>
    request<WebSearchOverview>(`${webSearchBase(id)}/sources`, { method: "POST", body: JSON.stringify(body) }),
  decide: (id: string, sourceId: string, state: "trusted" | "blocked") =>
    request<WebSearchOverview>(`${webSearchBase(id)}/sources/${encodeURIComponent(sourceId)}`, {
      method: "PATCH",
      body: JSON.stringify({ state }),
    }),
  remove: (id: string, sourceId: string) =>
    request<WebSearchOverview>(`${webSearchBase(id)}/sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" }),
  setMode: (id: string, mode: "open" | "trusted_only") =>
    request<WebSearchOverview>(`${webSearchBase(id)}/mode`, { method: "PUT", body: JSON.stringify({ mode }) }),
  canary: (id: string) =>
    request<{ provider: string | null; healthy: boolean; reason: string }>(`${webSearchBase(id)}/canary`, {
      method: "POST",
    }),
};

export const workspaceKnowledgeApi = {
  enable: (id: string) => request<Record<string, unknown>>(`${knowledgeBase(id)}/enable`, { method: "POST" }),
  sources: (id: string, limit?: number) =>
    request<SourceListing>(`${knowledgeBase(id)}/sources${limit ? `?limit=${limit}` : ""}`),
  sourcePage: (id: string, page: { limit?: number; cursor?: string | null; query?: string }) => {
    const params = new URLSearchParams();
    if (page.limit) params.set("limit", String(page.limit));
    if (page.cursor) params.set("cursor", page.cursor);
    if (page.query?.trim()) params.set("query", page.query.trim().slice(0, 200));
    const search = params.toString();
    return request<SourceListing>(`${knowledgeBase(id)}/sources${search ? `?${search}` : ""}`);
  },
  removeSource: (id: string, sourceId: string) =>
    request<Record<string, unknown>>(`${knowledgeBase(id)}/sources/${encodeURIComponent(sourceId)}`, {
      method: "DELETE",
    }),
  sourceDetail: (id: string, sourceId: string) =>
    request<SourceDetail>(`${knowledgeBase(id)}/sources/${encodeURIComponent(sourceId)}`),
  products: (id: string) => request<{ products: Record<string, string[]> }>(`${knowledgeBase(id)}/products`),
  upload: (id: string, form: FormData) =>
    request<UploadResult>(`${knowledgeBase(id)}/sources`, { method: "POST", body: form }),
  // The Knowledge settings read model (data classification and reranker admission); members may read it.
  settings: (id: string) => request<Record<string, unknown>>(`${knowledgeBase(id)}/settings`),
  search: (id: string, body: Record<string, unknown>) =>
    request<SearchResult>(`${knowledgeBase(id)}/search`, { method: "POST", body: JSON.stringify(body) }),
  evidenceWindow: async (id: string, evidenceKey: string) =>
    readEvidenceWindow(await request<unknown>(`${knowledgeBase(id)}/evidence/${encodeURIComponent(evidenceKey)}/window`)),
  packages: (id: string) => request<{ packages: KnowledgePackage[] }>(`${knowledgeBase(id)}/packages`),
  get: (id: string, packageId: string) =>
    request<KnowledgePackage>(`${knowledgeBase(id)}/packages/${encodeURIComponent(packageId)}`),
  researchPackage: (id: string, body: { topic: string; product?: string | null; versions?: string[] | null }) =>
    request<KnowledgePackage>(`${knowledgeBase(id)}/packages`, { method: "POST", body: JSON.stringify(body) }),
  researchMore: (id: string, packageId: string, instruction: string) =>
    request<KnowledgePackage>(`${knowledgeBase(id)}/packages/${encodeURIComponent(packageId)}/research`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),
  decide: (id: string, packageId: string, decisions: Record<string, "accepted" | "rejected">) =>
    request<KnowledgePackage>(`${knowledgeBase(id)}/packages/${encodeURIComponent(packageId)}/documents`, {
      method: "PATCH",
      body: JSON.stringify({ decisions }),
    }),
  addDocument: (id: string, packageId: string, entry: CatalogEntry) =>
    request<KnowledgePackage>(`${knowledgeBase(id)}/packages/${encodeURIComponent(packageId)}/documents`, {
      method: "POST",
      body: JSON.stringify(entry),
    }),
  editDocument: (id: string, packageId: string, documentId: string, entry: CatalogEntry) =>
    request<KnowledgePackage>(
      `${knowledgeBase(id)}/packages/${encodeURIComponent(packageId)}/documents/${encodeURIComponent(documentId)}`,
      { method: "PUT", body: JSON.stringify(entry) },
    ),
  removeDocument: (id: string, packageId: string, documentId: string) =>
    request<KnowledgePackage>(
      `${knowledgeBase(id)}/packages/${encodeURIComponent(packageId)}/documents/${encodeURIComponent(documentId)}`,
      { method: "DELETE" },
    ),
  approvePackage: (id: string, packageId: string, extractGraph: boolean) =>
    request<KnowledgePackage>(`${knowledgeBase(id)}/packages/${encodeURIComponent(packageId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ extract_graph: extractGraph }),
    }),
  graphStatus: (id: string) => request<GraphStatus>(`${knowledgeBase(id)}/graph`),
  extractGraph: (id: string, product: string, version: string | null) =>
    request<GraphStatus>(`${knowledgeBase(id)}/graph/extract`, {
      method: "POST",
      body: JSON.stringify({ product, version: version || null }),
    }),
  bindings: (id: string) => request<BindingsOverview>(`${knowledgeBase(id)}/bindings`),
  bind: (id: string, body: { source_workspace_id: string; products: string[]; reason: string }) =>
    request<BindingsOverview>(`${knowledgeBase(id)}/bindings`, { method: "POST", body: JSON.stringify(body) }),
  unbind: (id: string, bindingId: string) =>
    request<BindingsOverview>(`${knowledgeBase(id)}/bindings/${encodeURIComponent(bindingId)}`, { method: "DELETE" }),
  changes: (id: string, body: Record<string, unknown>) =>
    request<ChangesResult>(`${knowledgeBase(id)}/changes`, { method: "POST", body: JSON.stringify(body) }),
};
