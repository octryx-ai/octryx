// Collision-aware label placement for the relationship drawing. Labels are placed in priority order
// (selection, its neighbours, search matches, then by rank); a label whose estimated box would overlap
// an already placed label or any other node is shortened once and otherwise skipped. Exact names stay
// available through the node's SVG <title> and the entity list.

import { shortLabel, type ViewBox } from "./entityGraphReading";

export type LabelNode = { id: string; x: number; y: number; radius: number; display_name: string };
export type PlacedLabel = { text: string; x: number; y: number };
export type Box = { left: number; top: number; right: number; bottom: number };

// Average Inter glyph width as a share of the font size; deliberately generous so estimates err wide.
export const CHAR_WIDTH_EM = 0.6;
const ATTEMPT_CHARS = [24, 14];

function overlaps(a: Box, b: Box): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

function nodeBox(node: LabelNode): Box {
  return { left: node.x - node.radius, top: node.y - node.radius, right: node.x + node.radius, bottom: node.y + node.radius };
}

// The text box under a node: top a little below the circle, one line high, centred on the node.
export function labelBox(node: LabelNode, text: string, fontSize: number): Box {
  const half = (text.length * fontSize * CHAR_WIDTH_EM) / 2 + fontSize * 0.2;
  const top = node.y + node.radius + fontSize * 0.15;
  return { left: node.x - half, top, right: node.x + half, bottom: top + fontSize * 1.3 };
}

function inside(node: LabelNode, view: ViewBox | undefined): boolean {
  if (!view) return true;
  return node.x >= view.x && node.x <= view.x + view.w && node.y >= view.y && node.y <= view.y + view.h;
}

export function placeLabels(
  nodes: LabelNode[], order: string[], fontSize: number, view?: ViewBox, blocked: Box[] = [],
): Map<string, PlacedLabel> {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const placed = new Map<string, PlacedLabel>();
  // Boxes that win over any entity label (group names on the canvas).
  const taken: Box[] = [...blocked];
  const seen = new Set<string>();
  for (const id of order) {
    const node = byId.get(id);
    if (!node || seen.has(id) || !inside(node, view)) continue;
    seen.add(id);
    const name = node.display_name || "Unnamed entity";
    for (const max of ATTEMPT_CHARS) {
      const text = shortLabel(name, max);
      const box = labelBox(node, text, fontSize);
      const blocked = taken.some((other) => overlaps(box, other))
        || nodes.some((other) => other.id !== node.id && overlaps(box, nodeBox(other)));
      if (blocked) continue;
      taken.push(box);
      placed.set(id, { text, x: node.x, y: box.top + fontSize * 0.95 });
      break;
    }
  }
  return placed;
}
