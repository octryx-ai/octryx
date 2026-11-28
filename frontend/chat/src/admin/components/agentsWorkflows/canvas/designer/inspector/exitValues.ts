import type { DefNode, DesignerCatalog } from "../types";

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const list = (value: unknown) => (Array.isArray(value) ? value.map(text).filter(Boolean) : []);

const FIXED: Record<string, string[] | null> = {
  start: null, phase: null, review: null, pause: null, user_conversation: null,
  gate: ["passed", "failed"],
  user_confirmation: ["confirmed", "changed", "stopped"],
  approval: ["approved", "rejected"],
  platform_action: ["succeeded", "failed"],
  parallel_work: ["done", "replan"],
};
const SUBJECT_ROUTES: Record<string, string[]> = {
  functional_acceptance: ["accepted", "not_testable_yet", "rejected"],
};

export const OTHERWISE = "otherwise";

export function exitValues(node: DefNode, catalog: DesignerCatalog): string[] | null {
  const config = node.config ?? {};
  if (node.type === "decision") return config.check === "field" ? ["yes", "no"] : [...list(config.options), OTHERWISE];
  if (node.type === "watch") return list(config.conditions);
  if (node.type === "sub_workflow") return [...catalog.outcomes];
  if (node.type === "outcome") return [];
  if (node.type === "platform_action" && text(config.action)) {
    const action = catalog.platformActions.find((item) => item.key === text(config.action));
    return action?.routes.length ? [...action.routes] : FIXED.platform_action;
  }
  if (node.type === "user_confirmation" && SUBJECT_ROUTES[text(config.subject)])
    return SUBJECT_ROUTES[text(config.subject)];
  return node.type in FIXED ? FIXED[node.type] : null;
}

export function resultValues(node: DefNode, catalog: DesignerCatalog): string[] {
  if (node.type === "phase") return list(node.config?.result_values);
  if (node.type === "decision" || node.type === "outcome") return [];
  return exitValues(node, catalog) ?? [];
}

export function routableSources(nodes: DefNode[], self: string, catalog: DesignerCatalog): DefNode[] {
  return nodes.filter((node) => node.id !== self && resultValues(node, catalog).length > 0);
}
