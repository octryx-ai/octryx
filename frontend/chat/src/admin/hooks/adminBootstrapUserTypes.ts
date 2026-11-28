// Arguments of the admin user account actions.
import type { Dispatch, SetStateAction } from "react";
import type { AdminUser } from "../types/adminPanelTypes.usersProviders";

export type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

export type UseAdminBootstrapUserApprovalArgs = {
  readJson: ReadJsonFn;
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
