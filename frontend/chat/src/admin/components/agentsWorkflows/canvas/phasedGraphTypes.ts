export type NodeFamily =
  | "start" | "agent" | "parallel" | "action" | "person" | "wait" | "check" | "decision" | "subflow" | "end";
export type EdgeTone = "success" | "failure" | "neutral" | "loop";
export type Point = { x: number; y: number };

export type BoxBadge = {
  tone: "failure" | "loop"; label: string; target: string; title: string;
  edgeIds: string[]; when: string | null;
};

export type GraphBox = {
  id: string;
  kind: string;
  family: NodeFamily;
  kindLabel: string;
  kindLine: string;
  title: string;
  subtitle: string;
  errorPath: boolean;
  goodEnd: boolean;
  offPath: boolean;
  aside: boolean;
  badges: BoxBadge[];
};

export type GraphArrow = {
  id: string;
  edgeIds: string[];
  source: string;
  target: string;
  label: string;
  when: string | null;
  tone: EdgeTone;
  loop: boolean;
  maxIterations: number | null;
  title: string;
  badge: boolean;
  aside: boolean;
};

export type GroupKind = "phase" | "steps" | "manual";
export type GraphGroup = { id: string; title: string; family: NodeFamily; members: string[]; kind?: GroupKind };

export type PhasedGraph = { boxes: GraphBox[]; arrows: GraphArrow[]; groups: GraphGroup[] };

// Must match the node's CSS; the canvas measures the real size.
export const BOX_WIDTH = 240;
export const BOX_HEIGHT = 78;
export const BADGE_ROW = 22;
export const LAYER_GAP = 62;
export const COLUMN_GAP = 56;
export const LANE_GAP = 44;
export const GROUP_HEAD = 30;
export const GROUP_PAD = 12;

export function boxHeight(box: Pick<GraphBox, "badges">): number {
  return BOX_HEIGHT + box.badges.length * BADGE_ROW;
}
