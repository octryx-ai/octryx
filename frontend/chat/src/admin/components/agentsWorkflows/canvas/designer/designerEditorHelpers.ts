// Designer editor helpers: the empty catalog, request bodies, error text, typing detection and hand-made chart groups.
import type { GraphGroup } from "../phasedGraphTypes";
import type { DesignGroup } from "./modelCore";
import type { DesignerCatalog } from "./types";

export const EMPTY_CATALOG: DesignerCatalog = {
  agents: [], tools: [], checkTypes: [], gateCheckTypes: [], workflows: [], platformActions: [], confirmationSubjects: [],
  watchConditions: [], outcomes: ["blocked", "delivered", "done", "done_with_exception", "stopped"], deciders: ["requester"],
};

export const post = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
export const message = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);
export const typing = (target: EventTarget | null) => {
  const element = target as HTMLElement | null;
  return Boolean(element && (["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName) || element.isContentEditable));
};

// Hand-made groups as the chart draws them.
export function chartGroups(groups: DesignGroup[], known: Set<string>): GraphGroup[] {
  return groups.map((group) => ({
    id: group.id, title: group.label || "Group", family: "agent" as const, kind: "manual" as const,
    members: group.members.filter((id) => known.has(id)),
  })).filter((group) => group.members.length);
}
