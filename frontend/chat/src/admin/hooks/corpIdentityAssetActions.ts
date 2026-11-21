// Corporate identity profile assets: attach or clear the example deck, update or delete a template.
import type { Dispatch, SetStateAction } from "react";
import type { AdminCorpIdentityDetail, AdminCorpIdentityListResponse } from "../types/adminPanelTypes.runtimeCorp";

type CorpIdentityAssetActionArgs = {
  readJson: <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;
  corpIdentityDetail: AdminCorpIdentityDetail | null;
  setCorpIdentitySelectedId: Dispatch<SetStateAction<string | null>>;
  setCorpIdentityDetail: Dispatch<SetStateAction<AdminCorpIdentityDetail | null>>;
  setCorpIdentityActionBusy: Dispatch<SetStateAction<string | null>>;
  refreshCorpIdentities: (preferredProfileId?: string | null) => Promise<AdminCorpIdentityListResponse>;
  loadCorpIdentityDetail: (profileId: string | null) => Promise<AdminCorpIdentityDetail | null>;
};

export function createCorpIdentityAssetActions({
  readJson,
  corpIdentityDetail,
  setCorpIdentitySelectedId,
  setCorpIdentityDetail,
  setCorpIdentityActionBusy,
  refreshCorpIdentities,
  loadCorpIdentityDetail,
}: CorpIdentityAssetActionArgs) {
  const handleAttachExampleDeck = async (profileId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    setCorpIdentityActionBusy(`example:${profileId}`);
    try {
      const response = await fetch(
        `/admin/chat/api/panel/corp-identities/${encodeURIComponent(profileId)}/example-deck`,
        { method: "POST", credentials: "same-origin", body: form },
      );
      if (!response.ok) {
        let detail = response.statusText;
        try {
          const payload = (await response.json()) as { detail?: string };
          detail = payload.detail || detail;
        } catch {
          // Keep status text fallback.
        }
        throw new Error(detail || "Example deck upload failed");
      }
      const payload = (await response.json()) as {
        profile: AdminCorpIdentityDetail;
      };
      setCorpIdentitySelectedId(payload.profile.id);
      setCorpIdentityDetail(payload.profile);
      await refreshCorpIdentities(payload.profile.id);
    } finally {
      setCorpIdentityActionBusy(null);
    }
  };

  const handleClearExampleDeck = async (profileId: string) => {
    if (!window.confirm("Remove the example deck from this profile?")) {
      return;
    }
    setCorpIdentityActionBusy(`example-clear:${profileId}`);
    try {
      const payload = await readJson<{ profile: AdminCorpIdentityDetail }>(
        `/admin/chat/api/panel/corp-identities/${encodeURIComponent(profileId)}/example-deck`,
        { method: "DELETE" },
      );
      setCorpIdentityDetail(payload.profile);
      await refreshCorpIdentities(profileId);
    } finally {
      setCorpIdentityActionBusy(null);
    }
  };

  const handleUpdateTemplate = async (
    profileId: string,
    templateId: string,
    updates: Partial<{ display_name: string; description: string }>,
  ) => {
    setCorpIdentityActionBusy(`update:${templateId}`);
    try {
      const detail = await readJson<AdminCorpIdentityDetail>(
        `/admin/chat/api/panel/corp-identities/${encodeURIComponent(profileId)}/templates/${encodeURIComponent(templateId)}`,
        {
          method: "PUT",
          body: JSON.stringify(updates),
        },
      );
      setCorpIdentityDetail(detail);
      await refreshCorpIdentities(profileId);
    } finally {
      setCorpIdentityActionBusy(null);
    }
  };

  const handleDeleteTemplate = async (
    profileId: string,
    templateId: string,
    templateName: string,
  ) => {
    if (
      !window.confirm(
        `Delete template "${templateName}" from this profile? The file will not be deleted.`,
      )
    ) {
      return;
    }
    setCorpIdentityActionBusy(`delete-tpl:${templateId}`);
    try {
      await readJson<AdminCorpIdentityListResponse>(
        `/admin/chat/api/panel/corp-identities/${encodeURIComponent(profileId)}/templates/${encodeURIComponent(templateId)}`,
        { method: "DELETE" },
      );
      await refreshCorpIdentities(profileId);
      if (corpIdentityDetail?.id === profileId) {
        await loadCorpIdentityDetail(profileId);
      }
    } finally {
      setCorpIdentityActionBusy(null);
    }
  };

  return { handleAttachExampleDeck, handleClearExampleDeck, handleDeleteTemplate, handleUpdateTemplate };
}
