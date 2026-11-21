// Flow canvas viewport fitting: one refit when the palette or inspector changes the graph's size, and the initial fit.
import { useCallback, useEffect, useRef, type MutableRefObject } from "react";
import type { FlowDefinitionJson } from "./flowBuilderTypes";
import { FIT_VIEW } from "./flowCanvasView";
import { useRefitOnInspectorToggle } from "./flowInspectorRefit";
import { createPaletteRefit, type PaletteRefit } from "./flowPaletteRefit";

type FitView = (options: { padding: number; maxZoom: number; duration: number }) => unknown;

export function useFlowCanvasFit({
  fitView,
  initialized,
  definition,
  selectedNodeId,
  nodes,
}: {
  fitView: FitView;
  initialized: MutableRefObject<boolean>;
  definition: FlowDefinitionJson;
  selectedNodeId: string | null;
  nodes: readonly unknown[];
}) {
  // Opening or closing the palette changes the graph's width (it is a column beside the graph):
  // fit once after React Flow has the new size. Viewport only; the definition is never written.
  const graphRef = useRef<HTMLDivElement>(null);
  const paletteRefit = useRef<PaletteRefit | null>(null);
  useEffect(() => {
    const refit = createPaletteRefit({
      fit: () => {
        if (initialized.current) void fitView({ ...FIT_VIEW, duration: 250 });
      },
      frame: (callback) => {
        const id = window.requestAnimationFrame(callback);
        return () => window.cancelAnimationFrame(id);
      },
      timer: (callback, ms) => {
        const id = window.setTimeout(callback, ms);
        return () => window.clearTimeout(id);
      },
    });
    paletteRefit.current = refit;
    const element = graphRef.current;
    const observer =
      element && typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(([entry]) => refit.graphResized(entry.contentRect.width))
        : null;
    if (element && observer) observer.observe(element);
    return () => {
      observer?.disconnect();
      refit.dispose();
      paletteRefit.current = null;
    };
  }, [fitView]);
  const onPaletteCollapsedChange = useCallback(() => paletteRefit.current?.paletteToggled(), []);
  // The inspector takes space beside or below the graph like the palette does: same single refit.
  useRefitOnInspectorToggle(
    Boolean(selectedNodeId) && definition.nodes.some((node) => node.id === selectedNodeId),
    onPaletteCollapsedChange,
  );

  // Fit view once after initial render when container has real size
  useEffect(() => {
    if (nodes.length === 0 || !initialized.current) return;
    const id = requestAnimationFrame(() => {
      setTimeout(() => {
        if (nodes.length > 0 && initialized.current) {
          fitView({ ...FIT_VIEW, duration: 400 });
        }
      }, 50);
    });
    return () => cancelAnimationFrame(id);
  }, [nodes.length, fitView]);

  return { graphRef, onPaletteCollapsedChange };
}
