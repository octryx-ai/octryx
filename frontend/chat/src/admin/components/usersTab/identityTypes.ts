import type { FormEvent } from "react";

export type AdminReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type AdminUsersTabCtx = {
  users: AdminUserRow[];
  currentUserId?: string;
  readJson: AdminReadJsonFn;
  showCreateUser: boolean;
  setShowCreateUser: (value: boolean | ((value: boolean) => boolean)) => void;
  newUsername: string;
  setNewUsername: (value: string) => void;
  newEmail: string;
  setNewEmail: (value: string) => void;
  newPassword: string;
  setNewPassword: (value: string) => void;
  newDisplayName: string;
  setNewDisplayName: (value: string) => void;
  newAccountType: string;
  setNewAccountType: (value: string) => void;
  newRoles: string;
  setNewRoles: (value: string) => void;
  formError: string | null;
  formLoading: boolean;
  onCreateUser: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onRoleChange: (userId: string, roles: string[]) => void | Promise<void>;
  onDeactivateUser: (userId: string) => void | Promise<void>;
  onUpdateUser: (
    userId: string,
    payload: {
      username?: string;
      email?: string;
      display_name?: string;
      account_type?: string;
      group_ids?: string[];
      is_active?: boolean;
    },
  ) => Promise<AdminUserRow>;
  onResetUserPassword: (userId: string, password: string) => Promise<void>;
};

export type AdminUserRow = {
  id: string;
  username: string;
  email: string;
  display_name: string;
  account_type: string;
  roles: string[];
  groups: AdminIdentityGroupRow[];
  is_active: boolean;
};

export type AdminRoleRow = {
  id: string;
  name: string;
  description: string;
  is_core: boolean;
  user_count: number;
  permissions: AdminRolePermission[];
  assigned_users: AdminRoleAssignedUser[];
};

export type AdminRolePermission = {
  resource: string;
  action: string;
  // Catalog only: false = a check in the platform does not read this permission yet.
  enforced?: boolean;
};

export type AdminRoleAssignedUser = {
  id: string;
  username: string;
  email: string;
};

export type AdminEffectiveAccessRow = {
  user: {
    id: string;
    username: string;
    email: string;
    display_name: string;
    is_active: boolean;
  };
  roles: string[];
  groups: string[];
  permissions: AdminRolePermission[];
  assigned_projects: Array<{
    id: string;
    name: string;
    role: string;
  }>;
  effective: {
    can_use_chat: boolean;
    can_open_admin_panel: boolean;
    visible_project_count: number;
    assigned_project_count: number;
  };
  rules: string[];
};

export type AdminIdentityGroupRow = {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  rls_attributes: Array<{ key: string; value: string }>;
  member_count: number;
  created_at: string;
};

export type AdminUserApiKeyRow = {
  id: string;
  user_id: string;
  project_id: string | null;
  name: string;
  scopes: string[];
  key_prefix: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
};

export type AdminUserApiKeyCreateResponse = AdminUserApiKeyRow & {
  api_key: string;
};

export type AdminUserOidcIdentityRow = {
  id: string;
  provider_id: string;
  provider_name: string;
  provider_type: string;
  subject: string;
  external_email: string;
  external_username: string;
  external_groups: string[];
  profile: Record<string, unknown>;
  last_login_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminIdentityProviderRow = {
  id: string;
  name: string;
  providerType: string;
  issuerUrl: string;
  discoveryUrl: string;
  authorizationEndpoint: string;
  tokenEndpoint: string;
  userinfoEndpoint: string;
  jwksUri: string;
  clientId: string;
  scopes: string[];
  claimMappings: Record<string, string>;
  groupRoleMappings: Record<string, string[]>;
  groupGroupMappings: Record<string, string[]>;
  defaultRoles: string[];
  defaultGroupIds: string[];
  autoProvisionUsers: boolean;
  isActive: boolean;
  createdAt: string | null;
  updatedAt: string | null;
};
