import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";

const WORKSPACE_PANEL_WIDTH_STORAGE_KEY = "octryx-workspace-panel-width-v2";
const DEFAULT_WORKSPACE_PANEL_WIDTH = 560;
const MIN_WORKSPACE_PANEL_WIDTH = 440;
const MAX_WORKSPACE_PANEL_WIDTH = 760;
const MIN_MAIN_WORKSPACE_WIDTH = 700;

function getMaxWorkspacePanelWidth() {
  if (typeof window === "undefined") {
    return DEFAULT_WORKSPACE_PANEL_WIDTH;
  }
  return Math.max(
    MIN_WORKSPACE_PANEL_WIDTH,
    Math.min(
      MAX_WORKSPACE_PANEL_WIDTH,
      window.innerWidth - MIN_MAIN_WORKSPACE_WIDTH,
    ),
  );
}

function clampWorkspacePanelWidth(width: number) {
  return Math.min(
    Math.max(width, MIN_WORKSPACE_PANEL_WIDTH),
    getMaxWorkspacePanelWidth(),
  );
}

function readInitialWorkspacePanelWidth() {
  if (typeof window === "undefined") {
    return DEFAULT_WORKSPACE_PANEL_WIDTH;
  }
  const rawValue = window.localStorage.getItem(
    WORKSPACE_PANEL_WIDTH_STORAGE_KEY,
  );
  const parsedValue = Number(rawValue);
  return Number.isFinite(parsedValue)
    ? clampWorkspacePanelWidth(parsedValue)
    : clampWorkspacePanelWidth(DEFAULT_WORKSPACE_PANEL_WIDTH);
}

export function useWorkspacePanelLayout({ open }: { open: boolean }) {
  const [panelWidth, setPanelWidth] = useState(readInitialWorkspacePanelWidth);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(
      WORKSPACE_PANEL_WIDTH_STORAGE_KEY,
      String(panelWidth),
    );
  }, [panelWidth]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const handleResize = () => {
      setPanelWidth((current) => clampWorkspacePanelWidth(current));
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
    };
  }, []);

  const layoutStyle = useMemo(
    () =>
      open
        ? ({
            "--workspace-panel-width": `${panelWidth}px`,
          } as CSSProperties)
        : undefined,
    [open, panelWidth],
  );

  const handleResizeStart = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (typeof window === "undefined") {
      return;
    }
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = panelWidth;
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handlePointerMove = (moveEvent: MouseEvent) => {
      const nextWidth = clampWorkspacePanelWidth(
        startWidth - (moveEvent.clientX - startX),
      );
      setPanelWidth(nextWidth);
    };

    const handlePointerUp = () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("mouseup", handlePointerUp);
    };

    window.addEventListener("mousemove", handlePointerMove);
    window.addEventListener("mouseup", handlePointerUp);
  };

  return {
    layoutStyle,
    handleResizeStart,
  };
}
