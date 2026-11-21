// Phased workflow graph: box, arrow and group types, the nominal box sizes and gaps.

export type NodeFamily =
  | "start" | "agent" | "parallel" | "action" | "person" | "wait" | "check" | "decision" | "subflow" | "end";
export type EdgeTone = "success" | "failure" | "neutral" | "loop";
export type Point = { x: number; y: number };

// A loop or an exit into the error path, said on the box it leaves: "↻ back to Minimal fix (max 3)",
// "on failure → A step failed: retry, change or abort". A click opens the box it leads to.
export type BoxBadge = {
  tone: "failure" | "loop"; label: string; target: string; title: string;
  // The edges it stands for, and the result of the first (the designer selects that arrow).
  edgeIds: string[]; when: string | null;
};

export type GraphBox = {
  id: string;
  kind: string;
  family: NodeFamily;
  // The kind in words ("Agent phase", "Platform action").
  kindLabel: string;
  // The kind line the box shows: empty when the title already says it ("Start", "Independent review").
  kindLine: string;
  title: string;
  // One short line under the title ("engineer · 3 checks", "Creates a branch"); empty when it would only repeat the
  // title or the kind.
  subtitle: string;
  // On the error path (a failed action's pause, a blocked or stopped end).
  errorPath: boolean;
  // An end that delivered (done, delivered): drawn in the success tone.
  goodEnd: boolean;
  // Reached only through the error path: not drawn; a badge on the box before it opens it.
  offPath: boolean;
  // On the error path but drawn (a person decides there): its arrows are thin and shown on selection or hover.
  aside: boolean;
  badges: BoxBadge[];
};

export type GraphArrow = {
  id: string;
  // The definition edges this arrow stands for (two exits to the same node are one arrow "succeeded or failed").
  edgeIds: string[];
  source: string;
  target: string;
  label: string;
  // The result the (first) edge is taken for.
  when: string | null;
  tone: EdgeTone;
  loop: boolean;
  maxIterations: number | null;
  // The loop's own name in the definition ("Fix ↔ test"), for the tooltip.
  title: string;
  // Said as a badge on the source box instead of drawn: a loop, or an exit into the error path.
  badge: boolean;
  // Into or out of a box on the error path that is drawn: a thin line, shown on selection or hover.
  aside: boolean;
};

// A phase and the boxes that belong to it (its checks and confirmations right after it), a run of platform steps
// ("steps"), both derived from the graph, or boxes a person grouped by hand ("manual", layout.groups).
export type GroupKind = "phase" | "steps" | "manual";
export type GraphGroup = { id: string; title: string; family: NodeFamily; members: string[]; kind?: GroupKind };

export type PhasedGraph = { boxes: GraphBox[]; arrows: GraphArrow[]; groups: GraphGroup[] };

// Nominal box size the layout reserves (the node's CSS keeps it): the canvas measures the real one.
export const BOX_WIDTH = 240;
export const BOX_HEIGHT = 78;
// Each badge adds one line to its box.
export const BADGE_ROW = 22;
export const LAYER_GAP = 62;
export const COLUMN_GAP = 56;
export const LANE_GAP = 44;
// A group's frame around its boxes: the header line above them, a margin on the other sides.
export const GROUP_HEAD = 30;
export const GROUP_PAD = 12;

export function boxHeight(box: Pick<GraphBox, "badges">): number {
  return BOX_HEIGHT + box.badges.length * BADGE_ROW;
}
