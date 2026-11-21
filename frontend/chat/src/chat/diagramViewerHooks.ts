// State hooks of the diagram viewer: the XML it renders and the message bridge to the draw.io embed frame.
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { openDiagramInFullEditor, type DrawioEventData } from "./diagramViewerEditor";

// The XML actually rendered: the inline prop, or the full XML lazily fetched
// from the artifact endpoint when the inline copy is truncated/absent.
export function useDiagramXml(fetchUrl: string | undefined, xml: string | undefined) {
  const [resolvedXml, setResolvedXml] = useState(xml ?? "");
  const [fetching, setFetching] = useState(Boolean(fetchUrl));

  useEffect(() => {
    if (!fetchUrl) {
      setResolvedXml(xml ?? "");
      return;
    }
    let cancelled = false;
    setFetching(true);
    fetch(fetchUrl, { credentials: "include" })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((fullXml) => {
        if (cancelled) return;
        setResolvedXml(fullXml);
        setFetching(false);
      })
      .catch(() => {
        if (cancelled) return;
        // Fall back to whatever inline XML we have rather than showing nothing.
        setResolvedXml(xml ?? "");
        setFetching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchUrl, xml]);

  return { resolvedXml, fetching };
}

// The refs and state setters passed in are stable, so the hook deps behave as the component's own did.
type DrawioBridge = {
  iframeRef: RefObject<HTMLIFrameElement>;
  initializedRef: { current: boolean };
  resolvedXml: string;
  loaded: boolean;
  setLoaded: (loaded: boolean) => void;
  setError: (error: string | null) => void;
};

export function useDrawioBridge({ iframeRef, initializedRef, resolvedXml, loaded, setLoaded, setError }: DrawioBridge) {
  // Keep a stable ref to the current XML so the message handler always has the latest value
  const xmlRef = useRef(resolvedXml);
  xmlRef.current = resolvedXml;

  const sendToDrawio = useCallback((action: Record<string, unknown>) => {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    // draw.io requires "*" as targetOrigin — the frame may redirect internally
    win.postMessage(JSON.stringify(action), "*");
  }, [iframeRef]);

  // Handle messages FROM the draw.io embed frame
  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      // Only handle messages from our own iframe window
      if (event.source !== iframeRef.current?.contentWindow) return;
      // Ignore messages that are not strings (e.g. webpack HMR)
      if (typeof event.data !== "string") return;

      let data: DrawioEventData;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }

      if (data.event === "init") {
        initializedRef.current = true;
        sendToDrawio({ action: "load", xml: xmlRef.current });
        setLoaded(true);
      } else if (data.event === "load") {
        // After draw.io confirms the diagram is loaded, reset the view to fit all content
        sendToDrawio({ action: "resetView" });
      } else if (data.event === "error") {
        const msg = (data as { event: "error"; message: string }).message;
        setError(msg ?? "draw.io rendering error");
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [sendToDrawio, iframeRef, initializedRef, setLoaded, setError]);

  // Re-send XML when it changes after the editor has initialized (also fires
  // once the lazily-fetched full XML arrives).
  useEffect(() => {
    if (loaded && initializedRef.current && resolvedXml) {
      sendToDrawio({ action: "load", xml: resolvedXml });
    }
  }, [resolvedXml, loaded, sendToDrawio, initializedRef]);

  return xmlRef;
}

// Force an iframe reload by toggling its src.
function reloadFrame(iframe: HTMLIFrameElement | null) {
  if (iframe) {
    const src = iframe.src;
    iframe.src = "";
    requestAnimationFrame(() => {
      iframe.src = src;
    });
  }
}

type DiagramActions = Pick<DrawioBridge, "iframeRef" | "initializedRef" | "setLoaded" | "setError"> & {
  diagramId: string | undefined;
  xmlRef: { current: string };
};

// "Open in Editor" and "Retry"; refs and setters are stable, so both keep the identity they had in the component.
export function useDiagramActions({ diagramId, xmlRef, iframeRef, initializedRef, setLoaded, setError }: DiagramActions) {
  const handleOpenFullEditor = useCallback(() => {
    openDiagramInFullEditor(diagramId, xmlRef.current);
  }, [diagramId, xmlRef]);

  const handleRetry = useCallback(() => {
    initializedRef.current = false;
    setLoaded(false);
    setError(null);
    reloadFrame(iframeRef.current);
  }, [iframeRef, initializedRef, setLoaded, setError]);

  return { handleOpenFullEditor, handleRetry };
}
