import { readJson } from "../../utils/adminPanelHelpers";

export const SKILL_CATALOG_PATH = "/api/v1/admin/skill-catalog";

const url = (path: string) => `${SKILL_CATALOG_PATH}${path}`;
const id = (value: string) => encodeURIComponent(value);
const send = (path: string, method: string, body: unknown = {}, etag?: string) =>
  readJson<unknown>(url(path), {
    method,
    body: JSON.stringify(body),
    ...(etag ? { headers: { Accept: "application/json", "Content-Type": "application/json", "If-Match": etag } } : {}),
  });
const post = (path: string, body: unknown = {}) => send(path, "POST", body);

function query(filters: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && String(value).trim() !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export const loadSkills = (filters: Record<string, string | undefined> = {}) => readJson<unknown>(url(`/skills${query(filters)}`));
export const loadSkill = (skillId: string) => readJson<unknown>(url(`/skills/${id(skillId)}`));
export const createSkill = (body: unknown) => post("/skills", body);
export const editSkill = (skillId: string) => post(`/skills/${id(skillId)}/edit`);
export const loadVersion = (skillId: string, version: number) => readJson<unknown>(url(`/skills/${id(skillId)}/versions/${version}`));
/** Save the draft; `etag` is the digest the editor started from (409 `skill_draft_conflict` when it changed). */
export const saveDraft = (skillId: string, version: number, body: unknown, etag: string) =>
  send(`/skills/${id(skillId)}/versions/${version}`, "PUT", body, etag);
export const loadFile = (skillId: string, version: number, path: string) =>
  readJson<unknown>(url(`/skills/${id(skillId)}/versions/${version}/files${query({ path })}`));
export const loadDiff = (skillId: string, version: number, against: string = "published") =>
  readJson<unknown>(url(`/skills/${id(skillId)}/versions/${version}/diff${query({ against })}`));
export const loadDelivery = (skillId: string, version: number) =>
  readJson<unknown>(url(`/skills/${id(skillId)}/versions/${version}/delivery`));
export const submitVersion = (skillId: string, version: number) => post(`/skills/${id(skillId)}/versions/${version}/submit`);
/** `selfApprove`: the single-step publish the approval rule may allow (the server approves the own pending review). */
export const publishVersion = (skillId: string, version: number, approvalId: string | null, selfApprove = false) =>
  post(`/skills/${id(skillId)}/versions/${version}/publish`, selfApprove ? { self_approve: true } : { governance_approval_id: approvalId });
export const retireVersion = (skillId: string, version: number) => post(`/skills/${id(skillId)}/versions/${version}/retire`);
export const rollbackVersion = (skillId: string, version: number) => post(`/skills/${id(skillId)}/versions/${version}/rollback`);
export const approveReview = (approvalId: string) =>
  readJson<unknown>(`/api/v1/approvals/${id(approvalId)}/approve`, { method: "POST", body: JSON.stringify({ reason: "Skill version reviewed" }) });
export const rejectReview = (approvalId: string, reason: string) =>
  readJson<unknown>(`/api/v1/approvals/${id(approvalId)}/reject`, { method: "POST", body: JSON.stringify({ reason }) });
export const saveTags = (skillId: string, tags: string[]) => send(`/skills/${id(skillId)}/tags`, "PUT", { tags });
export const loadSkillWorkspaces = (skillId: string) => readJson<unknown>(url(`/skills/${id(skillId)}/workspaces`));
export const loadSkillUsage = (skillId: string, days = 30) => readJson<unknown>(url(`/skills/${id(skillId)}/usage${query({ days })}`));

export const checkUpstream = (skillId: string) => post(`/skills/${id(skillId)}/upstream/check`);
/** `path` only when the tracked folder is gone and the admin picked the new one. */
export const updateFromUpstream = (skillId: string, path?: string) => post(`/skills/${id(skillId)}/upstream/update`, path ? { path } : {});
export const saveTracking = (skillId: string, trackingMode: "pinned" | "follow") =>
  send(`/skills/${id(skillId)}/tracking`, "PUT", { tracking_mode: trackingMode });
export const checkSource = (sourceId: string) => post(`/sources/${id(sourceId)}/check`);
export const checkAllSources = () => post("/sources/check-all");

export const inspectSource = (body: unknown) => post("/import/inspect", body);
export const importFromGit = (body: unknown) => post("/import/git", body);
export function importUpload(file: File, categoryId: string, tags: string[]): Promise<unknown> {
  const form = new FormData();
  form.set("file", file);
  form.set("category_id", categoryId);
  form.set("tags", tags.join(","));
  // No Content-Type: the browser sets the multipart boundary.
  return readJson<unknown>(url("/import/upload"), { method: "POST", body: form, headers: { Accept: "application/json" } });
}

export const loadSources = () => readJson<unknown>(url("/sources"));
export const saveSource = (sourceId: string, body: unknown) => send(`/sources/${id(sourceId)}`, "PATCH", body);
export const saveSettings = (body: unknown) => send("/settings", "PUT", body);

export const loadCategories = () => readJson<unknown>(url("/categories"));
export const createCategory = (body: unknown) => post("/categories", body);
export const saveCategory = (categoryId: string, body: unknown) => send(`/categories/${id(categoryId)}`, "PATCH", body);
export const archiveCategory = (categoryId: string) => post(`/categories/${id(categoryId)}/archive`);
export const restoreCategory = (categoryId: string) => post(`/categories/${id(categoryId)}/restore`);

export const loadUsage = (days = 30) => readJson<unknown>(url(`/usage${query({ days })}`));

export const loadAssignment = (projectId: string) => readJson<unknown>(url(`/workspaces/${id(projectId)}/skills`));
export const saveAssignment = (projectId: string, body: unknown, etag: string) =>
  send(`/workspaces/${id(projectId)}/skills`, "PUT", body, etag);
