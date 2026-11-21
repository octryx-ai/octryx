import type { AdminRolePermission } from "./identityTypes";

export const DEFAULT_ROLE_PERMISSION_CATALOG: AdminRolePermission[] = [
  { resource: "users", action: "read" },
  { resource: "users", action: "write" },
  { resource: "api_keys", action: "read" },
  { resource: "api_keys", action: "write" },
  { resource: "api_keys", action: "self_read" },
  { resource: "api_keys", action: "self_write" },
  { resource: "auth", action: "login" },
  { resource: "roles", action: "read" },
  { resource: "roles", action: "write" },
  { resource: "projects", action: "read" },
  { resource: "projects", action: "write" },
  { resource: "providers", action: "read" },
  { resource: "providers", action: "write" },
  { resource: "runtimes", action: "read" },
  { resource: "runtimes", action: "write" },
  { resource: "knowledge", action: "read" },
  { resource: "knowledge", action: "write" },
  { resource: "tools", action: "read" },
  { resource: "tools", action: "write" },
  { resource: "audit", action: "read" },
];
