// Corporate identity admin state: profile list, selected detail and brief, upload, default, re-extract and delete.
import type { AdminCorpIdentityListResponse } from "../types/adminPanelTypes.runtimeCorp";
import { createCorpIdentityAssetActions } from "./corpIdentityAssetActions";
import {
  applyListPayload, deleteProfile, loadBrief, loadDetail, refreshList, reextractProfile, setDefaultProfile,
  uploadProfile,
} from "./corpIdentityProfileActions";
import { type ReadJsonFn, useCorpIdentityListLoad, useCorpIdentityState } from "./corpIdentityState";

type UseAdminCorpIdentityArgs = {
  readJson: ReadJsonFn;
  /** False for a non-admin: the profiles are admin-only, so the list is not requested at all. */
  enabled?: boolean;
};

export function useAdminCorpIdentity({ readJson, enabled = true }: UseAdminCorpIdentityArgs) {
  const state = useCorpIdentityState();
  useCorpIdentityListLoad(readJson, enabled, state);
  const ctx = { ...state, readJson };

  const loadCorpIdentityBrief = (profileId: string | null) => loadBrief(ctx, profileId);
  const loadCorpIdentityDetail = (profileId: string | null) => loadDetail(ctx, profileId);
  const applyCorpIdentityListPayload = (payload: AdminCorpIdentityListResponse, preferredProfileId?: string | null) =>
    applyListPayload(ctx, payload, preferredProfileId);
  const refreshCorpIdentities = (preferredProfileId?: string | null) => refreshList(ctx, preferredProfileId);
  const handleUploadCorpIdentity = (file: File, mergeIntoProfileId?: string | null) =>
    uploadProfile(ctx, file, mergeIntoProfileId);
  const handleSetDefaultCorpIdentity = (profileId: string) => setDefaultProfile(ctx, profileId);
  const handleReextractCorpIdentity = (profileId: string) => reextractProfile(ctx, profileId);
  const handleDeleteCorpIdentity = (profileId: string, name: string) => deleteProfile(ctx, profileId, name);

  const { handleAttachExampleDeck, handleClearExampleDeck, handleDeleteTemplate, handleUpdateTemplate } =
    createCorpIdentityAssetActions({
      readJson, corpIdentityDetail: state.corpIdentityDetail, setCorpIdentitySelectedId: state.setCorpIdentitySelectedId,
      setCorpIdentityDetail: state.setCorpIdentityDetail, setCorpIdentityActionBusy: state.setCorpIdentityActionBusy,
      refreshCorpIdentities, loadCorpIdentityDetail,
    });

  return {
    applyCorpIdentityListPayload,
    corpIdentityActionBusy: state.corpIdentityActionBusy,
    corpIdentityDefaultId: state.corpIdentityDefaultId,
    corpIdentityDetail: state.corpIdentityDetail,
    corpIdentityFileInputRef: state.corpIdentityFileInputRef,
    corpIdentityError: state.corpIdentityError,
    corpIdentityProfiles: state.corpIdentityProfiles,
    corpIdentitySelectedId: state.corpIdentitySelectedId,
    corpIdentityUploadBusy: state.corpIdentityUploadBusy,
    corpIdentityBrief: state.corpIdentityBrief,
    loadCorpIdentityBrief,
    handleAttachExampleDeck,
    handleClearExampleDeck,
    handleDeleteCorpIdentity,
    handleDeleteTemplate,
    handleReextractCorpIdentity,
    handleSetDefaultCorpIdentity,
    handleUpdateTemplate,
    handleUploadCorpIdentity,
    loadCorpIdentityDetail,
    refreshCorpIdentities,
  };
}
