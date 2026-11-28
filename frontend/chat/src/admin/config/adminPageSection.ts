import type { AdminTab } from "../types/adminPanelTypes.governance";

// Plain module state, no URL: the page takes it once when it mounts.
let pending: { tab: AdminTab; section: string } | null = null;

export function requestAdminSection(tab: AdminTab, section: string): void {
  pending = { tab, section };
}

export function takeAdminSection(tab: AdminTab): string | null {
  if (!pending || pending.tab !== tab) return null;
  const { section } = pending;
  pending = null;
  return section;
}
