// Designer model conversion: the phased definition to the model and back unchanged, the drawing direction, and
// what the flow chart draws.
import type { DefEdge, DefNode, NodeKind } from "./types";
import { clone, record, text, type Definition, type DesignModel, type Point, type Raw } from "./modelCore";

const SOURCE_KEYS = ["source_node_id", "source", "from_node_id", "from"];
const TARGET_KEYS = ["target_node_id", "target", "to_node_id", "to"];
const firstKey = (raw: Raw, keys: string[]) => keys.find((key) => text(raw[key])) ?? keys[0];

// --- Definition ⇄ model ----------------------------------------------------------------------------------------

export function fromDefinition(definition: Definition): DesignModel {
  const nodes: DefNode[] = [];
  const keepNodes: Record<string, Raw> = {};
  for (const raw of Array.isArray(definition.nodes) ? definition.nodes : []) {
    const node = record(raw);
    if (!node || !text(node.id) || keepNodes[text(node.id)]) continue;
    const id = text(node.id);
    keepNodes[id] = clone(node);
    const label = typeof node.label === "string" ? node.label : typeof node.title === "string" ? node.title : "";
    nodes.push({ id, type: text(node.type) as NodeKind, label, config: clone(record(node.config) ?? {}) });
  }
  const edges: DefEdge[] = [];
  const keepEdges: Record<string, Raw> = {};
  (Array.isArray(definition.edges) ? definition.edges : []).forEach((raw, index) => {
    const edge = record(raw);
    if (!edge) return;
    let id = text(edge.id) || `edge-${index + 1}`;
    while (keepEdges[id]) id = `${id}-${index + 1}`;
    keepEdges[id] = clone(edge);
    const max = edge.max_iterations;
    const label = typeof edge.label === "string" ? edge.label : typeof edge.title === "string" ? edge.title : undefined;
    edges.push({
      id,
      source: text(edge[firstKey(edge, SOURCE_KEYS)]),
      target: text(edge[firstKey(edge, TARGET_KEYS)]),
      kind: text(edge.kind) === "loop" ? "loop" : "next",
      when: text(edge.when) || null,
      max_iterations: typeof max === "number" && Number.isInteger(max) ? max : null,
      ...(label !== undefined ? { label } : {}),
    });
  });
  const layout = record(definition.layout);
  const ids = new Set(nodes.map((node) => node.id));
  const positions: Record<string, Point> = {};
  for (const [id, point] of Object.entries(record(layout?.positions) ?? {})) {
    const at = record(point);
    if (ids.has(id) && at && Number.isFinite(at.x) && Number.isFinite(at.y)) positions[id] = { x: at.x as number, y: at.y as number };
  }
  const groups = Array.isArray(layout?.groups)
    ? (layout!.groups as unknown[]).flatMap((raw) => {
      const group = record(raw);
      if (!group || !text(group.id)) return [];
      const members = (Array.isArray(group.members) ? group.members : []).filter((id): id is string => typeof id === "string");
      return [{ id: text(group.id), label: typeof group.label === "string" ? group.label : "", members }];
    })
    : null;
  const top = Object.fromEntries(Object.entries(definition).filter(([key]) => !["nodes", "edges", "layout"].includes(key)));
  return { nodes, edges, positions, groups, keep: { top: clone(top), nodes: keepNodes, edges: keepEdges, layout: layout ? clone(layout) : null } };
}

const sameJson = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function nodeOut(node: DefNode, raw: Raw | undefined): Raw {
  const out: Raw = { ...(raw ? clone(raw) : {}), id: node.id, type: node.type };
  const titled = raw && !("label" in raw) && "title" in raw;
  if (titled) out.title = node.label;
  else if (node.label || (raw && "label" in raw)) out.label = node.label;
  const hadConfig = raw && "config" in raw;
  if (Object.keys(node.config).length || hadConfig) {
    // A raw config that was not an object stays as it was while nobody changed it.
    out.config = hadConfig && !record(raw!.config) && !Object.keys(node.config).length ? raw!.config : clone(node.config);
  }
  return out;
}

function edgeOut(edge: DefEdge, raw: Raw | undefined, index: number): Raw {
  const out: Raw = raw ? clone(raw) : {};
  if (!raw || "id" in raw || edge.id !== `edge-${index + 1}`) out.id = edge.id;
  out[raw ? firstKey(raw, SOURCE_KEYS) : "source_node_id"] = edge.source;
  out[raw ? firstKey(raw, TARGET_KEYS) : "target_node_id"] = edge.target;
  const put = (key: string, value: unknown, fallback: unknown) => {
    if (value !== fallback || (raw && key in raw)) out[key] = value;
    else delete out[key];
  };
  put("kind", edge.kind, "next");
  put("when", edge.when, null);
  put("max_iterations", edge.max_iterations, null);
  const labelKey = raw && !("label" in raw) && "title" in raw ? "title" : "label";
  if (edge.label !== undefined) out[labelKey] = edge.label;
  else delete out[labelKey];
  return out;
}

export function toDefinition(model: DesignModel): Definition {
  const definition: Definition = clone(model.keep.top);
  definition.nodes = model.nodes.map((node) => nodeOut(node, model.keep.nodes[node.id]));
  definition.edges = model.edges.map((edge, index) => edgeOut(edge, model.keep.edges[edge.id], index));
  const block: Raw = Object.fromEntries(Object.entries(model.keep.layout ?? {}).filter(([key]) => key !== "positions" && key !== "groups"));
  const kept = model.keep.layout;
  if (Object.keys(model.positions).length || (kept && "positions" in kept && sameJson(kept.positions, {}))) {
    block.positions = Object.fromEntries(Object.entries(model.positions).map(([id, point]) => [id, { ...point }]));
  }
  if (model.groups !== null) block.groups = model.groups.map((group) => ({ ...group, members: [...group.members] }));
  if (Object.keys(block).length || kept) definition.layout = block;
  return definition;
}

// --- Drawing direction (layout.direction, display only) ------------------------------------------------------------

export const savedDirection = (model: DesignModel): unknown => model.keep.layout?.direction;

export function setDirection(model: DesignModel, direction: "tb" | "lr"): DesignModel {
  return { ...model, keep: { ...model.keep, layout: { ...(model.keep.layout ?? {}), direction } } };
}

// --- What the flow chart draws -----------------------------------------------------------------------------------

/** The editor payload's node and edge summaries (phased_editor._node_summary) of the model, for the flow chart. */
export function chartView(model: DesignModel) {
  const nodes = model.nodes.map((node) => {
    const config = node.config ?? {};
    const contract = record(config.workflow_contract) ?? {};
    const summary: Record<string, unknown> = { id: node.id, kind: node.type, title: node.label || node.id, config };
    for (const key of ["agent", "outcome", "subject", "question", "tool", "workflow_key", "conditions", "source", "options", "action", "output"]) {
      if (key in config) summary[key] = config[key];
    }
    if (node.type === "phase") {
      Object.assign(summary, {
        capability_class: contract.capability_class ?? null,
        steps: Array.isArray(contract.source_steps) ? contract.source_steps.length : 0,
        checks: Array.isArray(contract.checks) ? contract.checks.length : 0,
        path_rules: Array.isArray(record(contract.path_rules)?.write) ? record(contract.path_rules)!.write : [],
      });
    }
    if (node.type === "gate") summary.checks = Array.isArray(config.checks) ? config.checks.length : 0;
    return summary as { id: string; kind: string; title: string } & Record<string, unknown>;
  });
  const edges = model.edges.map((edge) => ({
    id: edge.id, source: edge.source, target: edge.target, kind: edge.kind, when: edge.when,
    max_iterations: edge.max_iterations, title: edge.label ?? "",
  }));
  return { nodes, edges };
}
