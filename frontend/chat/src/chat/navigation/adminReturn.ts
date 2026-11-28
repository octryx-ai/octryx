export type AdminReturn = { key: string; label: string; tab: "adminConnections" };

export const RETURN_PARAM = "return_to";

const RETURNS: Record<string, AdminReturn> = {
  "admin-connections": { key: "admin-connections", label: "Admin › Connections", tab: "adminConnections" },
};

export const RETURN_TO_CONNECTIONS: Record<string, string> = { [RETURN_PARAM]: "admin-connections" };

export function adminReturnOf(search: string): AdminReturn | null {
  const key = new URLSearchParams(search).get(RETURN_PARAM) ?? "";
  return RETURNS[key] ?? null;
}

export function currentAdminReturn(): AdminReturn | null {
  return typeof window === "undefined" ? null : adminReturnOf(window.location.search);
}
