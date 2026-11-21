import { useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

export function useCanvasRuntime({ selectedSessionId, streamToken, readJson }: {
  selectedSessionId: string | null;
  streamToken: string | null;
  readJson: ReadJsonFn;
}) {
  const [showCanvas, setShowCanvas] = useState(false);
  const [canvasId, setCanvasId] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<"pencil" | "rect" | "circle" | "eraser">("pencil");
  const [activeColor, setActiveColor] = useState("#ffffff");
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const canvasWsRef = useRef<WebSocket | null>(null);
  const isDrawingRef = useRef(false);
  const lastPosRef = useRef<{ x: number; y: number } | null>(null);

  const clearCanvas = () => clearCanvasOf(canvasRef);
  const drawElement = (element: any) => drawCanvasElement(canvasRef, element);
  const connectCanvasWs = (id: string) => connectCanvasSocket(id, streamToken, canvasWsRef, canvasRef);

  const openCanvas = async () => {
    if (!selectedSessionId) {
      return;
    }
    if (!canvasId) {
      try {
        const payload = await readJson<{ canvas_id: string }>(`/api/v1/canvas/sessions/${selectedSessionId}`, { method: "POST" });
        setCanvasId(payload.canvas_id);
        setShowCanvas(true);
        connectCanvasWs(payload.canvas_id);
      } catch {
        setShowCanvas(true);
      }
      return;
    }
    setShowCanvas((current) => {
      const next = !current;
      if (next && canvasId) {
        connectCanvasWs(canvasId);
      }
      return next;
    });
  };

  useEffect(() => {
    return () => {
      if (canvasWsRef.current) {
        canvasWsRef.current.close();
        canvasWsRef.current = null;
      }
    };
  }, []);

  return {
    showCanvas, setShowCanvas, activeTool, setActiveTool, activeColor, setActiveColor,
    canvasRef: canvasRef as MutableRefObject<HTMLCanvasElement | null>,
    canvasWsRef: canvasWsRef as MutableRefObject<WebSocket | null>,
    isDrawingRef, lastPosRef, clearCanvas, drawElement, openCanvas,
  };
}

type CanvasRef = MutableRefObject<HTMLCanvasElement | null>;

function clearCanvasOf(canvasRef: CanvasRef) {
  const canvas = canvasRef.current;
  if (!canvas) {
    return;
  }
  const context = canvas.getContext("2d");
  if (context) {
    context.clearRect(0, 0, canvas.width, canvas.height);
  }
}

function drawCanvasElement(canvasRef: CanvasRef, element: any) {
  const canvas = canvasRef.current;
  if (!canvas || !element) {
    return;
  }
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }
  context.strokeStyle = element.color || "#ffffff";
  context.lineWidth = element.tool === "eraser" ? 20 : 2;
  context.lineCap = "round";
  if (element.tool === "pencil" || element.tool === "eraser") {
    drawStroke(context, element);
    return;
  }
  if (element.tool === "rect") {
    context.strokeRect(element.x, element.y, element.w, element.h);
    return;
  }
  if (element.tool === "circle") {
    context.beginPath();
    context.ellipse(element.x + element.w / 2, element.y + element.h / 2, Math.abs(element.w / 2), Math.abs(element.h / 2), 0, 0, Math.PI * 2);
    context.stroke();
  }
}

// A pencil or eraser line through its points; the eraser cuts out what is under it.
function drawStroke(context: CanvasRenderingContext2D, element: any) {
  const points: { x: number; y: number }[] = element.points || [];
  if (points.length < 2) {
    return;
  }
  if (element.tool === "eraser") {
    context.globalCompositeOperation = "destination-out";
  }
  context.beginPath();
  context.moveTo(points[0].x, points[0].y);
  for (let index = 1; index < points.length; index += 1) {
    context.lineTo(points[index].x, points[index].y);
  }
  context.stroke();
  context.globalCompositeOperation = "source-over";
}

// One live socket per canvas: the server's state, draws and clears are replayed onto the canvas.
function connectCanvasSocket(id: string, streamToken: string | null, canvasWsRef: MutableRefObject<WebSocket | null>, canvasRef: CanvasRef) {
  if (canvasWsRef.current) {
    canvasWsRef.current.close();
  }
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const token = streamToken
    ? `?token=${encodeURIComponent(streamToken)}`
    : "";
  const socket = new WebSocket(
    `${protocol}://${location.host}/api/v1/canvas/sessions/${id}/ws${token}`,
  );
  socket.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.type === "state") {
        clearCanvasOf(canvasRef);
        (message.elements as any[]).forEach((element) => drawCanvasElement(canvasRef, element));
        return;
      }
      if (message.type === "draw") {
        drawCanvasElement(canvasRef, message.element);
        return;
      }
      if (message.type === "clear") {
        clearCanvasOf(canvasRef);
      }
    } catch {
      /* ignore malformed websocket events */
    }
  };
  canvasWsRef.current = socket;
}
