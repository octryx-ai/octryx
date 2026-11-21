import type { MutableRefObject } from "react";

import { CanvasCloseGlyph, CanvasToolbar } from "./CanvasToolbar";
import { canvasMouseDown, canvasMouseMove, canvasMouseUp, type CanvasTool } from "./canvasPointer";

type CanvasPanelProps = {
  activeTool: CanvasTool;
  setActiveTool: (next: CanvasTool) => void;
  activeColor: string;
  setActiveColor: (next: string) => void;
  setShowCanvas: (next: boolean) => void;
  canvasRef: MutableRefObject<HTMLCanvasElement | null>;
  canvasWsRef: MutableRefObject<WebSocket | null>;
  isDrawingRef: MutableRefObject<boolean>;
  lastPosRef: MutableRefObject<{ x: number; y: number } | null>;
  drawElement: (element: any) => void;
  clearCanvas: () => void;
};

export function CanvasPanel({
  activeTool,
  setActiveTool,
  activeColor,
  setActiveColor,
  setShowCanvas,
  canvasRef,
  canvasWsRef,
  isDrawingRef,
  lastPosRef,
  drawElement,
  clearCanvas,
}: CanvasPanelProps) {
  const pointer = { activeTool, activeColor, canvasWsRef, isDrawingRef, lastPosRef, drawElement };
  return (
    <div className="canvas-panel">
      <div className="canvas-panel__header">
        <div className="canvas-panel__heading">
          <div className="canvas-panel__eyebrow">Workspace canvas</div>
          <h3 className="canvas-panel__title">Canvas</h3>
        </div>
        <button
          type="button"
          className="canvas-tool-btn canvas-tool-btn--close"
          title="Close canvas"
          onClick={() => setShowCanvas(false)}
        >
          <CanvasCloseGlyph />
        </button>
      </div>
      <CanvasToolbar activeTool={activeTool} setActiveTool={setActiveTool} activeColor={activeColor}
        setActiveColor={setActiveColor} canvasWsRef={canvasWsRef} clearCanvas={clearCanvas} />
      <div className="canvas-panel__surface">
        <canvas
          ref={(element) => {
            canvasRef.current = element;
            if (element && element.width === 0) {
              element.width = element.offsetWidth || 800;
              element.height = element.offsetHeight || 280;
            }
          }}
          className="canvas-panel__canvas"
          onMouseDown={(event) => canvasMouseDown(pointer, event)}
          onMouseMove={(event) => canvasMouseMove(pointer, event)}
          onMouseUp={(event) => canvasMouseUp(pointer, event)}
        />
      </div>
    </div>
  );
}
