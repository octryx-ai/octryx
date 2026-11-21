// The canvas toolbar: drawing tools, colours, undo and clear.
import type { MutableRefObject, ReactNode } from "react";

import { type CanvasTool, sendCanvasCommand } from "./canvasPointer";

const TOOLS = ["pencil", "rect", "circle", "eraser"] as const;
const COLORS = ["#ffffff", "#ef4444", "#facc15", "#4ade80", "#60a5fa"];

function Glyph({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
    >
      {children}
    </svg>
  );
}

function ToolGlyph({ tool }: { tool: CanvasTool }) {
  return (
    <>
      {tool === "pencil" ? <Glyph><path d="M2 12L10 4l2 2-8 8H2v-2z" /></Glyph> : null}
      {tool === "rect" ? <Glyph><rect x="2" y="4" width="12" height="8" rx="1" /></Glyph> : null}
      {tool === "circle" ? <Glyph><circle cx="8" cy="8" r="5" /></Glyph> : null}
      {tool === "eraser" ? <Glyph><path d="M3 13l4-4 4 4M9 5l2 2-6 6H3v-2l6-6z" /></Glyph> : null}
    </>
  );
}

export function CanvasCloseGlyph() {
  return <Glyph><path d="M3 3l10 10M13 3L3 13" /></Glyph>;
}

export function CanvasToolbar({
  activeTool,
  setActiveTool,
  activeColor,
  setActiveColor,
  canvasWsRef,
  clearCanvas,
}: {
  activeTool: CanvasTool;
  setActiveTool: (next: CanvasTool) => void;
  activeColor: string;
  setActiveColor: (next: string) => void;
  canvasWsRef: MutableRefObject<WebSocket | null>;
  clearCanvas: () => void;
}) {
  return (
    <div className="canvas-toolbar">
      {TOOLS.map((tool) => (
        <button
          key={tool}
          type="button"
          className={`canvas-tool-btn ${activeTool === tool ? "canvas-tool-btn--active" : ""}`}
          onClick={() => setActiveTool(tool)}
          title={tool}
        >
          <ToolGlyph tool={tool} />
        </button>
      ))}
      <div className="canvas-toolbar__sep" />
      {COLORS.map((color) => (
        <button
          key={color}
          type="button"
          className={`canvas-color-btn ${activeColor === color ? "canvas-color-btn--active" : ""}`}
          style={{ background: color }}
          onClick={() => setActiveColor(color)}
          title={color}
        />
      ))}
      <div className="canvas-toolbar__sep" />
      <button type="button" className="canvas-tool-btn" title="Undo" onClick={() => sendCanvasCommand(canvasWsRef, "undo")}>
        <Glyph><path d="M3 8a5 5 0 1 0 1-3L1 3v4h4" /></Glyph>
      </button>
      <button
        type="button"
        className="canvas-tool-btn"
        title="Clear"
        onClick={() => {
          sendCanvasCommand(canvasWsRef, "clear");
          clearCanvas();
        }}
      >
        <Glyph><path d="M2 4h12M5 4V2h6v2M6 7v5M10 7v5M3 4l1 10h8l1-10" /></Glyph>
      </button>
      <div style={{ flex: 1 }} />
    </div>
  );
}
