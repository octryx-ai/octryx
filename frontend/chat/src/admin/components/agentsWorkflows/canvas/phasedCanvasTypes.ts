import type { Node } from "@xyflow/react";
import type { NodeKind } from "./designer/types";
import type { EdgeTone, GraphBox, GraphGroup, Point } from "./phasedGraphTypes";
import type { Frame } from "./phasedGroups";

export type CanvasEditing = {
  selectedIds: ReadonlySet<string>;
  selectedEdgeId: string | null;
  onSelectNode: (id: string, add: boolean) => void;
  onSelectEdge: (id: string) => void;
  onClear: () => void;
  onConnect: (source: string, target: string) => void;
  onDropBox: (kind: NodeKind, at: Point) => void;
  onMenu: (id: string) => void;
  onEditGroup: (id: string) => void;
  // A box added by click may land on a free spot outside the view.
  focus: { id: string; nonce: number } | null;
};

export type BoxData = GraphBox & {
  height: number;
  lr: boolean;
  editing: boolean;
  onOpen?: () => void;
  onBadge: (target: string, edgeIds: string[]) => void;
  onUnfold?: () => void;
  onMenu?: () => void;
};
export type GroupData = { title: string; count: number; kind: GraphGroup["kind"]; onFold: () => void; onEdit?: () => void };
export type ArrowData = {
  d: string; label: string; at: Point; tone: EdgeTone; title: string; aside: boolean; editing: boolean; selected: boolean;
  source: string; target: string; when: string | null; onSelect?: () => void;
};

export type CanvasNode = Node<BoxData> | Node<GroupData>;
export type Placement = { group: GraphGroup; frame: Frame; corner: Point };

export const shift = (point: Point, by: Point): Point => ({ x: point.x + by.x, y: point.y + by.y });
