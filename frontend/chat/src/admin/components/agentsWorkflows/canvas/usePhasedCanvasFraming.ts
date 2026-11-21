// The phased canvas's framing: the whole chart or its start when the set of boxes changes, and a new box in view.
import { useCallback, useEffect, useRef, useState } from "react";
import { useReactFlow } from "@xyflow/react";
import { BOX_HEIGHT, BOX_WIDTH, type GraphBox, type PhasedGraph, type Point } from "./phasedGraphTypes";
import { type GraphLayout } from "./phasedGraphLayout";
import type { CanvasEditing } from "./phasedCanvasTypes";

type PhasedCanvasFramingInput = {
  graph: PhasedGraph;
  layout: GraphLayout;
  positions: Map<string, Point>;
  drawn: GraphBox[];
  width: number;
  height: number;
  editing: boolean;
  lr: boolean;
  edit?: CanvasEditing;
  view: Pick<ReturnType<typeof useReactFlow>, "fitView" | "setViewport" | "setCenter" | "getZoom">;
};

export function usePhasedCanvasFraming({
  graph, layout, positions, drawn, width, height, editing, lr, edit, view,
}: PhasedCanvasFramingInput) {
  const { fitView, setViewport, setCenter, getZoom } = view;
  // Framing when the workflow (its set of boxes) changes: the whole chart when it is readable, else its start at a
  // readable zoom (a long workflow); the Fit button of the controls always shows all of it. While editing, a chart
  // that fits readably is framed whole again when a box comes or goes; a long one keeps its view and a new box is
  // brought into view on its own (`edit.focus`).
  const [ready, setReady] = useState(false);
  const framedOnce = useRef(false);
  const shape = `${layout.direction}|${graph.boxes.map((box) => box.id).join("|")}`;
  const positionsRef = useRef(positions);
  positionsRef.current = new Map(drawn.flatMap((box) => (positions.has(box.id) ? [[box.id, positions.get(box.id)!] as const] : [])));
  // The boxes' positions arrive one render after the boxes themselves: frame once every box has one.
  const placed = graph.boxes.every((box) => positions.has(box.id));
  const frame = useCallback(() => {
    const points = [...positionsRef.current.values()];
    if (!points.length || !width || !height) return;
    const minX = Math.min(...points.map((point) => point.x)) - 140;
    const maxX = Math.max(...points.map((point) => point.x)) + BOX_WIDTH + 60;
    const minY = Math.min(...points.map((point) => point.y)) - 30;
    const maxY = Math.max(...points.map((point) => point.y)) + BOX_HEIGHT + 40;
    const fit = Math.min(width / (maxX - minX), height / (maxY - minY), 1);
    if (editing && fit < 0.6 && framedOnce.current) return;
    framedOnce.current = true;
    if (fit >= 0.6) {
      if (editing) {
        // From the positions themselves: a box just added is not measured yet, so fitView would leave it out.
        const zoom = Math.min(1, 0.92 * fit);
        void setViewport({ x: (width - (maxX - minX) * zoom) / 2 - minX * zoom, y: (height - (maxY - minY) * zoom) / 2 - minY * zoom, zoom });
        return;
      }
      void fitView({ padding: 0.1, maxZoom: 1 });
      return;
    }
    if (lr) {
      const zoom = Math.max(0.6, Math.min(0.85, height / (maxY - minY)));
      void setViewport({ x: -minX * zoom + 20, y: (height - (maxY - minY) * zoom) / 2 - minY * zoom, zoom });
      return;
    }
    const zoom = Math.max(0.6, Math.min(0.85, width / (maxX - minX)));
    void setViewport({ x: (width - (maxX - minX) * zoom) / 2 - minX * zoom, y: -minY * zoom, zoom });
    // Only a new set of boxes, a new direction or a resized canvas re-frames; moving a box keeps the view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, placed, width, height, fitView, setViewport]);
  useEffect(() => {
    if (!ready || !placed) return undefined;
    const timer = window.setTimeout(frame, 30);
    return () => window.clearTimeout(timer);
  }, [ready, placed, frame]);
  const focus = edit?.focus;
  useEffect(() => {
    if (!focus || !ready) return undefined;
    const timer = window.setTimeout(() => {
      // A chart that fits readably is framed whole (above); only a long one moves to the box.
      const points = [...positionsRef.current.values()];
      const spanX = Math.max(...points.map((point) => point.x)) - Math.min(...points.map((point) => point.x)) + BOX_WIDTH + 200;
      const spanY = Math.max(...points.map((point) => point.y)) - Math.min(...points.map((point) => point.y)) + BOX_HEIGHT + 70;
      if (width && height && Math.min(width / spanX, height / spanY) >= 0.6) return;
      const point = positionsRef.current.get(focus.id);
      if (point) void setCenter(point.x + BOX_WIDTH / 2, point.y + BOX_HEIGHT / 2, { zoom: Math.max(getZoom(), 0.7) });
    }, 60);
    return () => window.clearTimeout(timer);
  }, [focus, ready, setCenter, getZoom, width, height]);

  return setReady;
}
