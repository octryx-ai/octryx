// Designer model core: the model and its types, value helpers, ids, lookups and the ways forward of a box.
import { exitValues } from "./inspector/exitValues";
import type { DefEdge, DefNode, DesignerCatalog, NodeKind } from "./types";

export type Point = { x: number; y: number };
export type DesignGroup = { id: string; label: string; members: string[] };
export type Definition = Record<string, unknown>;
export type Raw = Record<string, unknown>;

export type DesignModel = {
  nodes: DefNode[];
  edges: DefEdge[];
  // Hand-set box positions (top-left); a box without one is placed by the automatic layout.
  positions: Record<string, Point>;
  // Hand-made groups; null: none were ever made, the canvas draws its own (a phase and its checks).
  groups: DesignGroup[] | null;
  // End boxes the designer placed itself (never moved by hand): they stay right of the last box (not saved).
  autoEnds?: string[];
  // Everything the conversion keeps to write the definition back as it was.
  keep: {
    top: Definition;
    nodes: Record<string, Raw>;
    edges: Record<string, Raw>;
    layout: Raw | null;
  };
};

// How often a new way back may be taken before the run goes on (the person changes it in the arrow's panel).
export const DEFAULT_LOOP_LIMIT = 2;
// Undo keeps this many steps.
export const HISTORY_LIMIT = 100;

export const clone = <T>(value: T): T => (value === undefined ? value : JSON.parse(JSON.stringify(value)) as T);
export const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
export const record = (value: unknown): Raw | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Raw) : null;

// --- Ids and lookups ---------------------------------------------------------------------------------------------

export const ID_STEMS: Partial<Record<NodeKind, string>> = {
  phase: "step", gate: "check", decision: "condition", outcome: "end", platform_action: "action",
  user_conversation: "question", user_confirmation: "confirm", approval: "approval", sub_workflow: "subflow",
};

export function uniqueId(stem: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  for (let n = 1; ; n += 1) {
    const id = `${stem}-${n}`;
    if (!used.has(id)) return id;
  }
}

export const nodeIds = (model: DesignModel) => model.nodes.map((node) => node.id);
export const edgeIds = (model: DesignModel) => model.edges.map((edge) => edge.id);

export const findNode = (model: DesignModel, id: string | null | undefined) => model.nodes.find((node) => node.id === id);
export const findEdge = (model: DesignModel, id: string | null | undefined) => model.edges.find((edge) => edge.id === id);

/** The boxes before ``id`` on the way forward (its ancestors over the next arrows). */
export function ancestors(model: DesignModel, id: string): Set<string> {
  const seen = new Set<string>();
  const stack = [id];
  while (stack.length) {
    const current = stack.pop()!;
    for (const edge of model.edges) {
      if (edge.kind === "next" && edge.target === current && !seen.has(edge.source)) {
        seen.add(edge.source);
        stack.push(edge.source);
      }
    }
  }
  return seen;
}

/** An arrow from ``source`` to ``target`` goes back (a loop) when the target comes before the source, or is it. */
export const isBackEdge = (model: DesignModel, source: string, target: string) =>
  source === target || ancestors(model, source).has(target);

/** The results an arrow out of ``source`` can stand for (null: one way out), and those not taken yet. */
export function routeChoices(model: DesignModel, source: string, catalog: DesignerCatalog): string[] | null {
  const node = findNode(model, source);
  return node ? exitValues(node, catalog) : null;
}

export function freeRoutes(model: DesignModel, source: string, catalog: DesignerCatalog): string[] | null {
  const choices = routeChoices(model, source, catalog);
  if (choices === null) return null;
  const taken = new Set(model.edges.filter((edge) => edge.source === source).map((edge) => edge.when));
  return choices.filter((value) => !taken.has(value));
}

export function withoutMembers(groups: DesignGroup[] | null, gone: Set<string>): DesignGroup[] | null {
  if (groups === null) return null;
  return groups.map((group) => ({ ...group, members: group.members.filter((id) => !gone.has(id)) }))
    .filter((group) => group.members.length);
}
