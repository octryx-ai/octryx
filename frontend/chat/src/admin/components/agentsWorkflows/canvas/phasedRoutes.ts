// The routes of the flow chart's arrows. Pure: orthogonal corners from a box's exit to
// the next box's top through the layout's waypoints, rounded into an SVG path, and where each arrow's label sits.
import { BOX_HEIGHT, BOX_WIDTH, LAYER_GAP, type GraphArrow, type Point } from "./phasedGraphTypes";
import { LR_LAYER_GAP, type GraphLayout } from "./phasedGraphLayout";

// Orthogonal corner points from a box's exit to the next box's top, through the waypoints (box-centre height of the
// layers in between); turns happen in the gap above the next stop, so a line never runs through a box. `side`: the
// arrow leaves from the source's right edge (the error path) and goes right first, then down.
export function arrowCorners(start: Point, end: Point, waypoints: Point[], side: boolean): Point[] {
  const points: Point[] = [start];
  let current = start;
  const stops = [...waypoints.map((point) => ({ point, top: point.y - BOX_HEIGHT / 2 })), { point: end, top: end.y }];
  stops.forEach(({ point, top }, index) => {
    if (index === 0 && side && point.x !== current.x) {
      points.push({ x: point.x, y: current.y }, point);
    } else if (point.x === current.x) {
      points.push(point);
    } else {
      let turn = top - LAYER_GAP / 2;
      if (turn < current.y) turn = (current.y + point.y) / 2;
      points.push({ x: current.x, y: turn }, { x: point.x, y: turn }, point);
    }
    current = point;
  });
  return points.filter((point, index) => {
    const previous = points[index - 1];
    return !previous || previous.x !== point.x || previous.y !== point.y;
  });
}

// An SVG path through the corners with rounded turns.
export function roundedPath(points: Point[], radius = 8): string {
  if (!points.length) return "";
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    const next = points[index + 1];
    if (!next) {
      path += ` L ${point.x} ${point.y}`;
      break;
    }
    const previous = points[index - 1];
    const inLength = Math.hypot(point.x - previous.x, point.y - previous.y);
    const outLength = Math.hypot(next.x - point.x, next.y - point.y);
    const r = Math.min(radius, inLength / 2, outLength / 2);
    if (r <= 0) {
      path += ` L ${point.x} ${point.y}`;
      continue;
    }
    const before = { x: point.x - ((point.x - previous.x) / inLength) * r, y: point.y - ((point.y - previous.y) / inLength) * r };
    const after = { x: point.x + ((next.x - point.x) / outLength) * r, y: point.y + ((next.y - point.y) / outLength) * r };
    path += ` L ${before.x} ${before.y} Q ${point.x} ${point.y} ${after.x} ${after.y}`;
  }
  return path;
}

// Where an arrow's label sits, so two exits of one box never share a spot: on the sideways leg of an error exit, in
// the middle of a straight arrow, else on the longest leg before the final approach (a branch's own lane).
export function labelPoint(points: Point[]): Point {
  const legs = points.slice(1).map((point, index) => ({ a: points[index], b: point }));
  const middle = ({ a, b }: { a: Point; b: Point }) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
  const length = ({ a, b }: { a: Point; b: Point }) => Math.hypot(b.x - a.x, b.y - a.y);
  if (!legs.length) return points[0] ?? { x: 0, y: 0 };
  if (legs.length === 1) return middle(legs[0]);
  if (legs[0].a.y === legs[0].b.y && length(legs[0]) >= 28) return middle(legs[0]);
  const candidates = legs.length > 2 ? legs.slice(0, -1) : legs;
  return middle(candidates.reduce((best, leg) => (length(leg) > length(best) ? leg : best)));
}

// A loop's label sits on the middle of its lane (the long way up), never on the short leg beside the box, where it
// would run under the box.
export function loopLabelPoint(arrow: Pick<GraphArrow, "loop" | "source" | "target">, points: Point[]): Point | null {
  if (!arrow.loop || arrow.source === arrow.target || points.length !== 4) return null;
  return { x: points[1].x, y: (points[1].y + points[2].y) / 2 };
}

const samePoint = (a: Point | undefined, b: Point | undefined) =>
  Boolean(a && b && Math.round(a.x) === Math.round(b.x) && Math.round(a.y) === Math.round(b.y));

// The gap between two loop lanes beside the chart.
export const LOOP_LANE = 18;

// The corners of every drawn arrow from the boxes' current positions (`positions` holds only what is drawn).
// Waypoints only while both ends sit where the auto-layout put them; a moved box gets a plain orthogonal route.
export function arrowRoutes(
  arrows: GraphArrow[], positions: Map<string, Point>, layout: GraphLayout, heights: Map<string, number> = layout.heights,
): Map<string, Point[]> {
  const result = new Map<string, Point[]>();
  const height = (id: string) => heights.get(id) ?? BOX_HEIGHT;
  // Arrows that go back up (loops) run in their own lane right of every box they pass, one lane per arrow.
  let lane = 0;
  for (const arrow of arrows) {
    if (arrow.badge) continue;
    const s = positions.get(arrow.source);
    const t = positions.get(arrow.target);
    if (!s || !t) continue;
    if (layout.direction === "lr") {
      result.set(arrow.id, sidewaysCorners(s, t, height(arrow.source), height(arrow.target)));
      continue;
    }
    // A loop back to the same box: a small hook on its right side.
    if (arrow.source === arrow.target) {
      const right = s.x + BOX_WIDTH;
      const out = right + 22 + lane * LOOP_LANE;
      lane += 1;
      result.set(arrow.id, [
        { x: right, y: s.y + BOX_HEIGHT * 0.7 }, { x: out, y: s.y + BOX_HEIGHT * 0.7 }, { x: out, y: s.y + BOX_HEIGHT * 0.3 },
        { x: right, y: s.y + BOX_HEIGHT * 0.3 },
      ]);
      continue;
    }
    // A loop, or a box placed above the one before it by hand: out of the source's right side, up a lane right of
    // every box between the two, into the target's right side. Never through a box.
    if (t.y < s.y + height(arrow.source)) {
      const top = t.y;
      const bottom = s.y + height(arrow.source);
      const passed = [...positions].filter(([, point]) => point.y < bottom && point.y + BOX_HEIGHT > top);
      const edge = Math.max(s.x, t.x, ...passed.map(([, point]) => point.x)) + BOX_WIDTH;
      const side = edge + 28 + lane * LOOP_LANE;
      lane += 1;
      const from = { x: s.x + BOX_WIDTH, y: s.y + BOX_HEIGHT / 2 };
      const to = { x: t.x + BOX_WIDTH, y: t.y + BOX_HEIGHT / 2 };
      result.set(arrow.id, [from, { x: side, y: from.y }, { x: side, y: to.y }, to]);
      continue;
    }
    const home = samePoint(s, layout.positions.get(arrow.source)) && samePoint(t, layout.positions.get(arrow.target));
    const waypoints = home ? layout.routes.get(arrow.id) ?? [] : [];
    const firstX = waypoints[0]?.x ?? t.x + BOX_WIDTH / 2;
    // Sideways only when no other box sits in the way on the source's row.
    const midY = s.y + BOX_HEIGHT / 2;
    const clear = ![...positions].some(([id, point]) => id !== arrow.source && id !== arrow.target
      && point.y < midY && point.y + height(id) > midY && point.x < firstX && point.x + BOX_WIDTH > s.x + BOX_WIDTH);
    const side = arrow.tone === "failure" && firstX > s.x + BOX_WIDTH && clear;
    const start = side ? { x: s.x + BOX_WIDTH, y: s.y + BOX_HEIGHT / 2 } : { x: s.x + BOX_WIDTH / 2, y: s.y + height(arrow.source) };
    result.set(arrow.id, arrowCorners(start, { x: t.x + BOX_WIDTH / 2, y: t.y }, waypoints, side));
  }
  return result;
}

// Left to right: from the source's right edge to the target's left edge, turning in the gap before the target; an
// arrow to a box that is not further right runs below both boxes.
export function sidewaysCorners(s: Point, t: Point, sourceHeight: number, targetHeight: number): Point[] {
  const start = { x: s.x + BOX_WIDTH, y: s.y + BOX_HEIGHT / 2 };
  const end = { x: t.x, y: t.y + BOX_HEIGHT / 2 };
  if (end.x > start.x) {
    if (end.y === start.y) return [start, end];
    const turn = Math.max(start.x + 12, end.x - LR_LAYER_GAP / 2);
    return [start, { x: turn, y: start.y }, { x: turn, y: end.y }, end];
  }
  const below = Math.max(s.y + sourceHeight, t.y + targetHeight) + 24;
  const from = { x: s.x + BOX_WIDTH / 2, y: s.y + sourceHeight };
  const to = { x: t.x + BOX_WIDTH / 2, y: t.y + targetHeight };
  return [from, { x: from.x, y: below }, { x: to.x, y: below }, to];
}
