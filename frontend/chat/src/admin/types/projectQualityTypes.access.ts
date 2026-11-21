// Workspace access assignment, user, role and group types.
export type AdminProjectAccessAssignment = {
  user_id: string;
  username: string;
  email: string;
  display_name: string;
  is_active: boolean;
  project_role: string;
  project_roles?: string[];
  granted_by: string | null;
  granted_at: string | null;
};

export type AdminProjectGroupAccessAssignment = {
  group_id: string;
  name: string;
  description: string;
  is_active: boolean;
  project_role: string;
  project_roles?: string[];
  granted_by: string | null;
  granted_at: string | null;
};

export type AdminProjectRoleAccessAssignment = {
  role_id: string;
  role: string;
  project_roles?: string[];
  granted_by: string | null;
  granted_at: string | null;
};

export type AdminProjectAccessUser = {
  id: string;
  username: string;
  email: string;
  display_name: string;
  is_active: boolean;
  roles: string[];
  groups: string[];
};

export type AdminProjectAccessRole = {
  id: string;
  name: string;
  description: string;
};

export type AdminProjectAccessGroup = {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
};

export type AdminProjectAccessPayload = {
  project: {
    id: string;
    name: string;
    is_active: boolean;
  };
  assignments: AdminProjectAccessAssignment[];
  group_assignments: AdminProjectGroupAccessAssignment[];
  role_assignments: AdminProjectRoleAccessAssignment[];
  available_users: AdminProjectAccessUser[];
  available_roles: AdminProjectAccessRole[];
  available_groups: AdminProjectAccessGroup[];
  group_assignments_supported: boolean;
  rules: string[];
};
