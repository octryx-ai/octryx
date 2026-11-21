import type { ReactNode } from "react";

// Menu entries of an admin-shell area that open a page in another component of the same area (the
// Agents area's Clients and Rules pages beside its builder pages). Same look as the shell's own entries, icon
// included, so one menu never mixes entries with and without icons.
// `position: "end"` lists the entry after the group's own pages (default: before them).
export type AdminExternalNavEntry = { group: string; key: string; label: string; icon: ReactNode; onSelect: () => void; position?: "start" | "end" };

export function AdminExternalNavButtons({ entries }: { entries: AdminExternalNavEntry[] }) {
  return (
    <>
      {entries.map((entry) => (
        <div key={entry.key} className="admin-panel__tab-tree">
          <button type="button" className="admin-panel__tab" onClick={entry.onSelect} aria-label={entry.label}
            title={entry.label} data-entry={entry.key}>
            {entry.icon}
            <span className="admin-panel__tab-label">{entry.label}</span>
          </button>
        </div>
      ))}
    </>
  );
}

/** External entries whose group the area has no group of its own; they come first, grouped by label. */
export function externalOnlyGroups(entries: AdminExternalNavEntry[], ownGroups: string[]): Array<{ label: string; entries: AdminExternalNavEntry[] }> {
  const groups: Array<{ label: string; entries: AdminExternalNavEntry[] }> = [];
  for (const entry of entries) {
    if (ownGroups.includes(entry.group)) continue;
    const group = groups.find((item) => item.label === entry.group);
    if (group) group.entries.push(entry);
    else groups.push({ label: entry.group, entries: [entry] });
  }
  return groups;
}
