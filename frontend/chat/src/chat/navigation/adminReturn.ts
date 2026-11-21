// The way back to Admin from a page Admin opens in another area: Admin › Connections lists
// Repositories and Jira write-back, which are still pages of Coding and Work. Opening them adds `return_to` to the
// address, and the page then shows a "← Admin › Connections" link above it until the area is left. Pure, no React.

export type AdminReturn = { key: string; label: string; tab: "adminConnections" };

export const RETURN_PARAM = "return_to";

const RETURNS: Record<string, AdminReturn> = {
  "admin-connections": { key: "admin-connections", label: "Admin › Connections", tab: "adminConnections" },
};

/** The address fields that open a page of another area with a way back to Admin › Connections. */
export const RETURN_TO_CONNECTIONS: Record<string, string> = { [RETURN_PARAM]: "admin-connections" };

/** Where the page opened from Admin leads back to, or null when it was not opened from Admin. */
export function adminReturnOf(search: string): AdminReturn | null {
  const key = new URLSearchParams(search).get(RETURN_PARAM) ?? "";
  return RETURNS[key] ?? null;
}

/** The way back for the current address (none outside a browser). */
export function currentAdminReturn(): AdminReturn | null {
  return typeof window === "undefined" ? null : adminReturnOf(window.location.search);
}
