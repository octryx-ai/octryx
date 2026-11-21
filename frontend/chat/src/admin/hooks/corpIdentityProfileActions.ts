// Corporate identity profile requests: brief, detail, list refresh, upload, default, re-extract and delete.
import type { AdminCorpIdentityDetail, AdminCorpIdentityListResponse } from "../types/adminPanelTypes.runtimeCorp";
import type { CorpIdentityState, ReadJsonFn } from "./corpIdentityState";

export type CorpIdentityContext = CorpIdentityState & { readJson: ReadJsonFn };

const profileUrl = (profileId: string) =>
  `/admin/chat/api/panel/corp-identities/${encodeURIComponent(profileId)}`;

export async function loadBrief(ctx: CorpIdentityContext, profileId: string | null) {
  if (!profileId) {
    ctx.setCorpIdentityBrief(null);
    return null;
  }
  try {
    const brief = await ctx.readJson<Record<string, unknown>>(
      `${profileUrl(profileId)}/corporate-identity`,
    );
    ctx.setCorpIdentityBrief(brief);
    return brief;
  } catch {
    ctx.setCorpIdentityBrief(null);
    return null;
  }
}

export async function loadDetail(ctx: CorpIdentityContext, profileId: string | null) {
  if (!profileId) {
    ctx.setCorpIdentitySelectedId(null);
    ctx.setCorpIdentityDetail(null);
    ctx.setCorpIdentityBrief(null);
    return null;
  }
  const detail = await ctx.readJson<AdminCorpIdentityDetail>(profileUrl(profileId));
  ctx.setCorpIdentitySelectedId(profileId);
  ctx.setCorpIdentityDetail(detail);
  void loadBrief(ctx, profileId);
  return detail;
}

export async function applyListPayload(
  ctx: CorpIdentityContext,
  payload: AdminCorpIdentityListResponse,
  preferredProfileId?: string | null,
) {
  const profiles = payload.profiles || [];
  ctx.setCorpIdentityProfiles(profiles);
  ctx.setCorpIdentityDefaultId(payload.default_profile_id || "");
  const known = (id: string | null | undefined) => (id && profiles.some((item) => item.id === id) ? id : null);
  const resolvedProfileId =
    known(preferredProfileId) ||
    known(ctx.corpIdentitySelectedId) ||
    payload.default_profile_id ||
    profiles[0]?.id ||
    null;
  if (!resolvedProfileId) {
    ctx.setCorpIdentitySelectedId(null);
    ctx.setCorpIdentityDetail(null);
    return payload;
  }
  await loadDetail(ctx, resolvedProfileId);
  return payload;
}

export async function refreshList(ctx: CorpIdentityContext, preferredProfileId?: string | null) {
  const payload = await ctx.readJson<AdminCorpIdentityListResponse>(
    "/admin/chat/api/panel/corp-identities",
  );
  return applyListPayload(ctx, payload, preferredProfileId);
}

async function uploadErrorDetail(response: Response) {
  let detail = response.statusText;
  try {
    const payload = (await response.json()) as { detail?: string };
    detail = payload.detail || detail;
  } catch {
    // Keep status text fallback.
  }
  return detail;
}

export async function uploadProfile(ctx: CorpIdentityContext, file: File, mergeIntoProfileId?: string | null) {
  const form = new FormData();
  form.append("file", file);
  if (mergeIntoProfileId) {
    form.append("merge", "true");
    form.append("profile_id", mergeIntoProfileId);
  }
  ctx.setCorpIdentityUploadBusy(true);
  try {
    const params = mergeIntoProfileId
      ? `?merge=true&profile_id=${encodeURIComponent(mergeIntoProfileId)}`
      : "";
    const response = await fetch(`/admin/chat/api/panel/corp-identities/upload${params}`, {
      method: "POST",
      credentials: "same-origin",
      body: form,
    });
    if (!response.ok) {
      const detail = await uploadErrorDetail(response);
      throw new Error(detail || "Corporate identity upload failed");
    }
    const payload = (await response.json()) as { profile: AdminCorpIdentityDetail };
    ctx.setCorpIdentitySelectedId(payload.profile.id);
    ctx.setCorpIdentityDetail(payload.profile);
    await refreshList(ctx, payload.profile.id);
  } finally {
    ctx.setCorpIdentityUploadBusy(false);
    if (ctx.corpIdentityFileInputRef.current) {
      ctx.corpIdentityFileInputRef.current.value = "";
    }
  }
}

export async function setDefaultProfile(ctx: CorpIdentityContext, profileId: string) {
  ctx.setCorpIdentityActionBusy(`default:${profileId}`);
  try {
    await ctx.readJson<AdminCorpIdentityListResponse>(`${profileUrl(profileId)}/default`, { method: "POST" });
    await refreshList(ctx, profileId);
  } finally {
    ctx.setCorpIdentityActionBusy(null);
  }
}

export async function reextractProfile(ctx: CorpIdentityContext, profileId: string) {
  ctx.setCorpIdentityActionBusy(`reextract:${profileId}`);
  try {
    const payload = await ctx.readJson<{ profile: AdminCorpIdentityDetail }>(
      `${profileUrl(profileId)}/reextract`,
      { method: "POST" },
    );
    ctx.setCorpIdentitySelectedId(profileId);
    ctx.setCorpIdentityDetail(payload.profile);
    await refreshList(ctx, profileId);
  } finally {
    ctx.setCorpIdentityActionBusy(null);
  }
}

export async function deleteProfile(ctx: CorpIdentityContext, profileId: string, name: string) {
  if (!window.confirm(`Delete corporate identity profile "${name}"?`)) {
    return;
  }
  ctx.setCorpIdentityActionBusy(`delete:${profileId}`);
  try {
    await ctx.readJson<AdminCorpIdentityListResponse>(profileUrl(profileId), { method: "DELETE" });
    const selected = ctx.corpIdentitySelectedId;
    await refreshList(ctx, selected === profileId ? null : selected);
  } finally {
    ctx.setCorpIdentityActionBusy(null);
  }
}
