// The phased canvas: what the editor hands in while editing, the data of boxes, groups and arrows, and placements.
import type { Node } from "@xyflow/react";
import type { NodeKind } from "./designer/types";
import type { EdgeTone, GraphBox, GraphGroup, Point } from "./phasedGraphTypes";
import type { Frame } from "./phasedGroups";

// What the canvas needs while the workflow is edited; the editor owns the model, the selection and every change.
export type CanvasEditing = {
  selectedIds: ReadonlySet<string>;
  selectedEdgeId: string | null;
  // A click on a box (with Shift, Ctrl or Cmd: added to the selection), on an arrow, on the empty canvas.
  onSelectNode: (id: string, add: boolean) => void;
  onSelectEdge: (id: string) => void;
  onClear: () => void;
  onConnect: (source: string, target: string) => void;
  onDropBox: (kind: NodeKind, at: Point) => void;
  onMenu: (id: string) => void;
  onEditGroup: (id: string) => void;
  // Brings this box into view (a box added by click lands on a free spot that may lie outside the view).
  focus: { id: string; nonce: number } | null;
};

export type BoxData = GraphBox & {
  height: number;
  lr: boolean;
  editing: boolean;
  onOpen?: () => void;
  onBadge: (target: string, edgeIds: string[]) => void;
  // A folded group's box: unfolds it.
  onUnfold?: () => void;
  onMenu?: () => void;
};
export type GroupData = { title: string; count: number; kind: GraphGroup["kind"]; onFold: () => void; onEdit?: () => void };
export type ArrowData = {
  d: string; label: string; at: Point; tone: EdgeTone; title: string; aside: boolean; editing: boolean; selected: boolean;
  source: string; target: string; when: string | null; onSelect?: () => void;
};

export type CanvasNode = Node<BoxData> | Node<GroupData>;
// Where each group stands: its frame (unfolded) or its box (folded, at the frame's top-left box corner).
export type Placement = { group: GraphGroup; frame: Frame; corner: Point };

export const shift = (point: Point, by: Point): Point => ({ x: point.x + by.x, y: point.y + by.y });
