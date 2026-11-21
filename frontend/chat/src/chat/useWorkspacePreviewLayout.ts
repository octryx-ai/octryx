import { useEffect, useMemo, useRef, useState } from "react";
import type {
  CSSProperties,
  MouseEvent as ReactMouseEvent,
  RefObject,
} from "react";

const WORKSPACE_PREVIEW_RATIO_STORAGE_KEY = "octryx-workspace-preview-ratio-v2";
const DEFAULT_WORKSPACE_PREVIEW_RATIO = 0.6;
const MIN_WORKSPACE_PREVIEW_RATIO = 0.5;
const MAX_WORKSPACE_PREVIEW_RATIO = 0.72;

function clampPreviewRatio(value: number) {
  return Math.min(
    Math.max(value, MIN_WORKSPACE_PREVIEW_RATIO),
    MAX_WORKSPACE_PREVIEW_RATIO,
  );
}

function readInitialPreviewRatio() {
  if (typeof window === "undefined") {
    return DEFAULT_WORKSPACE_PREVIEW_RATIO;
  }
  const rawValue = Number(
    window.localStorage.getItem(WORKSPACE_PREVIEW_RATIO_STORAGE_KEY),
  );
  return Number.isFinite(rawValue)
    ? clampPreviewRatio(rawValue)
    : DEFAULT_WORKSPACE_PREVIEW_RATIO;
}

export function useWorkspacePreviewLayout({ enabled }: { enabled: boolean }): {
  containerRef: RefObject<HTMLDivElement>;
  layoutStyle: CSSProperties | undefined;
  handleResizeStart: (event: ReactMouseEvent<HTMLDivElement>) => void;
} {
  const containerRef = useRef<HTMLDivElement>(null);
  const [previewRatio, setPreviewRatio] = useState(readInitialPreviewRatio);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(
      WORKSPACE_PREVIEW_RATIO_STORAGE_KEY,
      String(previewRatio),
    );
  }, [previewRatio]);

  const layoutStyle = useMemo(
    () =>
      enabled
        ? ({
            "--workspace-preview-width": `${Math.round(previewRatio * 100)}%`,
          } as CSSProperties)
        : undefined,
    [enabled, previewRatio],
  );

  const handleResizeStart = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (typeof window === "undefined") {
      return;
    }
    const container = containerRef.current;
    if (!container) {
      return;
    }
    event.preventDefault();
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handlePointerMove = (moveEvent: MouseEvent) => {
      const bounds = container.getBoundingClientRect();
      if (!bounds.width) {
        return;
      }
      const nextRatio = clampPreviewRatio(
        (moveEvent.clientX - bounds.left) / bounds.width,
      );
      setPreviewRatio(nextRatio);
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
    containerRef,
    layoutStyle,
    handleResizeStart,
  };
}
