// Mouse drawing on the workspace canvas: strokes for pencil and eraser, shapes for rect and circle.
import type { MouseEvent, MutableRefObject } from "react";

export type CanvasTool = "pencil" | "rect" | "circle" | "eraser";

export type CanvasPointerArgs = {
  activeTool: CanvasTool;
  activeColor: string;
  canvasWsRef: MutableRefObject<WebSocket | null>;
  isDrawingRef: MutableRefObject<boolean>;
  lastPosRef: MutableRefObject<{ x: number; y: number } | null>;
  drawElement: (element: any) => void;
};

const freehand = (tool: CanvasTool) => tool === "pencil" || tool === "eraser";

function pointerPosition(event: MouseEvent<HTMLCanvasElement>) {
  const rect = (event.target as HTMLCanvasElement).getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

export function canvasMouseDown(args: CanvasPointerArgs, event: MouseEvent<HTMLCanvasElement>) {
  args.isDrawingRef.current = true;
  args.lastPosRef.current = pointerPosition(event);
  if (freehand(args.activeTool)) {
    (event.target as any)._currentStroke = {
      tool: args.activeTool,
      color: args.activeColor,
      points: [args.lastPosRef.current],
    };
  } else {
    (event.target as any)._shapeStart = args.lastPosRef.current;
  }
}

export function canvasMouseMove(args: CanvasPointerArgs, event: MouseEvent<HTMLCanvasElement>) {
  if (!args.isDrawingRef.current) {
    return;
  }
  const canvas = event.target as HTMLCanvasElement;
  const position = pointerPosition(event);
  if (freehand(args.activeTool)) {
    const stroke = (canvas as any)._currentStroke;
    if (stroke) {
      stroke.points.push(position);
      args.drawElement(stroke);
    }
  }
  args.lastPosRef.current = position;
}

export function canvasMouseUp(args: CanvasPointerArgs, event: MouseEvent<HTMLCanvasElement>) {
  if (!args.isDrawingRef.current) {
    return;
  }
  args.isDrawingRef.current = false;
  const canvas = event.target as HTMLCanvasElement;
  const position = pointerPosition(event);
  let element: any = null;
  if (freehand(args.activeTool)) {
    element = (canvas as any)._currentStroke;
    (canvas as any)._currentStroke = null;
  } else {
    const start = (canvas as any)._shapeStart || position;
    element = {
      tool: args.activeTool,
      color: args.activeColor,
      x: start.x,
      y: start.y,
      w: position.x - start.x,
      h: position.y - start.y,
    };
    args.drawElement(element);
    (canvas as any)._shapeStart = null;
  }
  if (element && args.canvasWsRef.current?.readyState === 1) {
    args.canvasWsRef.current.send(JSON.stringify({ type: "draw", element }));
  }
}

/** Sends one canvas command (undo, clear) to the shared canvas when its socket is open. */
export function sendCanvasCommand(canvasWsRef: MutableRefObject<WebSocket | null>, type: "undo" | "clear") {
  if (canvasWsRef.current?.readyState === 1) {
    canvasWsRef.current.send(JSON.stringify({ type }));
  }
}
