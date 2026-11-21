// Designer model copy and paste: the boxes (never the start) with the arrows between them, renamed on paste.
import type { DefEdge, DefNode } from "./types";
import { clone, edgeIds, findNode, ID_STEMS, nodeIds, uniqueId, type DesignModel, type Point } from "./modelCore";
import { removable } from "./modelEditing";

export type Clipboard = { nodes: DefNode[]; edges: DefEdge[]; positions: Record<string, Point> };

/** The boxes (never the start) and the arrows between them. */
export function copyItems(model: DesignModel, ids: string[]): Clipboard | null {
  const chosen = new Set(ids.filter((id) => removable(findNode(model, id))));
  if (!chosen.size) return null;
  return clone({
    nodes: model.nodes.filter((node) => chosen.has(node.id)),
    edges: model.edges.filter((edge) => chosen.has(edge.source) && chosen.has(edge.target)),
    positions: Object.fromEntries(Object.entries(model.positions).filter(([id]) => chosen.has(id))),
  });
}

// Config keys that name another box: a copy names the copied box when that was copied along.
const NODE_REFS = ["source", "phase"];

export const PASTE_OFFSET = 40;

export function paste(model: DesignModel, clip: Clipboard, offset: Point = { x: PASTE_OFFSET, y: PASTE_OFFSET }): { model: DesignModel; ids: string[] } {
  const taken = new Set(nodeIds(model));
  const renamed = new Map<string, string>();
  for (const node of clip.nodes) {
    const id = uniqueId(ID_STEMS[node.type] ?? node.type.replace(/_/g, "-"), taken);
    taken.add(id);
    renamed.set(node.id, id);
  }
  const nodes = clip.nodes.map((node) => {
    const config = clone(node.config);
    for (const key of NODE_REFS) {
      if (typeof config[key] === "string" && renamed.has(config[key] as string)) config[key] = renamed.get(config[key] as string);
    }
    return { ...node, id: renamed.get(node.id)!, label: node.label ? `${node.label} (copy)` : node.label, config };
  });
  const edgesTaken = new Set(edgeIds(model));
  const edges = clip.edges.map((edge) => {
    const source = renamed.get(edge.source)!;
    const id = uniqueId(`e-${source}`, edgesTaken);
    edgesTaken.add(id);
    return { ...clone(edge), id, source, target: renamed.get(edge.target)! };
  });
  const positions = { ...model.positions };
  for (const [id, point] of Object.entries(clip.positions)) {
    positions[renamed.get(id)!] = { x: point.x + offset.x, y: point.y + offset.y };
  }
  return { model: { ...model, nodes: [...model.nodes, ...nodes], edges: [...model.edges, ...edges], positions }, ids: [...renamed.values()] };
}
