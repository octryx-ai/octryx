import type { AdminTab } from "../types/adminPanelTypes.governance";

// A register to open inside an Admin page, requested by a link from elsewhere (an Advanced pointer opens
// Models › Defaults on its Coding engine tab). The page takes it once when it mounts; plain module state, no URL.
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
