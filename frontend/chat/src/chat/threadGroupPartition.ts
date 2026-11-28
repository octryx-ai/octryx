// Absence from the selectable list does not prove a workspace is archived, so the section never claims that.
// While the selectable list is not loaded (empty) nothing moves, so the sidebar does not flicker.
type GroupLike = { projectId?: string; sessions: unknown[]; totalThreadCount?: number };

export function partitionThreadGroups<T extends GroupLike>(groups: T[], selectableProjectIds: Set<string>) {
  const active: T[] = [];
  const other: T[] = [];
  for (const group of groups) {
    const projectId = (group.projectId || "").trim();
    if (!projectId || selectableProjectIds.size === 0 || selectableProjectIds.has(projectId)) active.push(group);
    else other.push(group);
  }
  const otherThreadCount = other.reduce(
    (total, group) => total + (group.totalThreadCount ?? group.sessions.length), 0);
  return { active, other, otherThreadCount };
}
