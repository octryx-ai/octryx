import { clone, nodeIds, uniqueId, withoutMembers, type DesignGroup, type DesignModel } from "./modelCore";

/** `current` keeps the drawn groups, so the first hand-made change does not drop back to none. */
export function createGroup(model: DesignModel, members: string[], label: string, current: DesignGroup[]): { model: DesignModel; id: string | null } {
  const known = new Set(nodeIds(model));
  const chosen = [...new Set(members.filter((id) => known.has(id)))];
  if (!chosen.length) return { model, id: null };
  const base = withoutMembers(model.groups ?? clone(current), new Set(chosen)) ?? [];
  const id = uniqueId("group", base.map((group) => group.id));
  return { model: { ...model, groups: [...base, { id, label: label.trim() || "Group", members: chosen }] }, id };
}

export function renameGroup(model: DesignModel, id: string, label: string, current: DesignGroup[]): DesignModel {
  const base = model.groups ?? clone(current);
  return { ...model, groups: base.map((group) => (group.id === id ? { ...group, label } : group)) };
}

export function dissolveGroup(model: DesignModel, id: string, current: DesignGroup[]): DesignModel {
  const base = model.groups ?? clone(current);
  return { ...model, groups: base.filter((group) => group.id !== id) };
}
