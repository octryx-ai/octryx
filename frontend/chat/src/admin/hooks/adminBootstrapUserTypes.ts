// Arguments of the admin bootstrap and user account actions.
import type { Dispatch, SetStateAction } from "react";
import type { AdminProvider, AdminUser, LocalBootstrapStatus, SetupGuideStatus } from "../types/adminPanelTypes.usersProviders";
import type { AdminRuntime, AdminRuntimeSettings } from "../types/adminPanelTypes.runtimeCorp";

export type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

export type UseAdminBootstrapUserApprovalArgs = {
  readJson: ReadJsonFn;
  setLocalBootstrap: Dispatch<SetStateAction<LocalBootstrapStatus | null>>;
  setLocalBootstrapEndpointDraft: Dispatch<SetStateAction<string>>;
  setLocalBootstrapModelDraft: Dispatch<SetStateAction<string>>;
  setLocalBootstrapDisplayDraft: Dispatch<SetStateAction<string>>;
  setSetupGuide: Dispatch<SetStateAction<SetupGuideStatus | null>>;
  setLocalBootstrapLoading: Dispatch<SetStateAction<boolean>>;
  setLocalBootstrapError: Dispatch<SetStateAction<string | null>>;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  setRuntimes: Dispatch<SetStateAction<AdminRuntime[]>>;
  setRuntimeSettings: Dispatch<SetStateAction<AdminRuntimeSettings>>;
  setRuntimeDefaultModelDraft: Dispatch<SetStateAction<string>>;
  setTabError: Dispatch<SetStateAction<string | null>>;
  loadTab: (tab: string) => Promise<void>;
  setUsers: Dispatch<SetStateAction<AdminUser[]>>;
  setFormError: Dispatch<SetStateAction<string | null>>;
  setFormLoading: Dispatch<SetStateAction<boolean>>;
  newUsername: string;
  newEmail: string;
  newPassword: string;
  newDisplayName: string;
  newAccountType: string;
  newRoles: string;
  setShowCreateUser: Dispatch<SetStateAction<boolean>>;
  setNewUsername: Dispatch<SetStateAction<string>>;
  setNewEmail: Dispatch<SetStateAction<string>>;
  setNewPassword: Dispatch<SetStateAction<string>>;
  setNewDisplayName: Dispatch<SetStateAction<string>>;
  setNewAccountType: Dispatch<SetStateAction<string>>;
  setNewRoles: Dispatch<SetStateAction<string>>;
};
