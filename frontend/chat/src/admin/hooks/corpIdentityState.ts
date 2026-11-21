// Corporate identity admin state and the initial profile list load.
import { useEffect, useRef, useState } from "react";
import type { AdminCorpIdentityDetail, AdminCorpIdentityListResponse, AdminCorpIdentityProfile } from "../types/adminPanelTypes.runtimeCorp";

export type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

export function useCorpIdentityState() {
  const [corpIdentityError, setCorpIdentityError] = useState("");
  const [corpIdentityProfiles, setCorpIdentityProfiles] = useState<
    AdminCorpIdentityProfile[]
  >([]);
  const [corpIdentityDefaultId, setCorpIdentityDefaultId] = useState("");
  const [corpIdentitySelectedId, setCorpIdentitySelectedId] = useState<
    string | null
  >(null);
  const [corpIdentityDetail, setCorpIdentityDetail] =
    useState<AdminCorpIdentityDetail | null>(null);
  const [corpIdentityUploadBusy, setCorpIdentityUploadBusy] = useState(false);
  const [corpIdentityActionBusy, setCorpIdentityActionBusy] = useState<
    string | null
  >(null);
  const corpIdentityFileInputRef = useRef<HTMLInputElement | null>(null);
  const [corpIdentityBrief, setCorpIdentityBrief] = useState<Record<
    string,
    unknown
  > | null>(null);
  return {
    corpIdentityError, setCorpIdentityError,
    corpIdentityProfiles, setCorpIdentityProfiles,
    corpIdentityDefaultId, setCorpIdentityDefaultId,
    corpIdentitySelectedId, setCorpIdentitySelectedId,
    corpIdentityDetail, setCorpIdentityDetail,
    corpIdentityUploadBusy, setCorpIdentityUploadBusy,
    corpIdentityActionBusy, setCorpIdentityActionBusy,
    corpIdentityFileInputRef,
    corpIdentityBrief, setCorpIdentityBrief,
  };
}

export type CorpIdentityState = ReturnType<typeof useCorpIdentityState>;

export function useCorpIdentityListLoad(
  readJson: ReadJsonFn,
  enabled: boolean,
  { setCorpIdentityProfiles, setCorpIdentityDefaultId, setCorpIdentityError }: CorpIdentityState,
) {
  useEffect(() => {
    if (!enabled) return undefined;
    let disposed = false;
    void (async () => {
      try {
        const payload = await readJson<AdminCorpIdentityListResponse>(
          "/admin/chat/api/panel/corp-identities",
        );
        if (disposed) return;
        setCorpIdentityProfiles(payload.profiles || []);
        setCorpIdentityDefaultId(payload.default_profile_id || "");
      } catch (error) {
        if (!disposed)
          setCorpIdentityError(
            error instanceof Error
              ? error.message
              : "Corporate identity could not be loaded.",
          );
      }
    })();
    return () => {
      disposed = true;
    };
  }, [readJson, enabled, setCorpIdentityProfiles, setCorpIdentityDefaultId, setCorpIdentityError]);
}
