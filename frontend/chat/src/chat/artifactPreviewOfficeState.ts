// State of the Office artifact preview: the inspect payload, the action catalog, the rendered preview and the
// labels derived from the current inspector mode.
import { useEffect, useMemo, useState } from "react";
import type { ToolArtifact } from "../chatThreadTypes";
import { artifactExtension } from "./artifactPreviewKind";
import { inspectOfficeUrl, officeActionsUrl, resolveOfficeAction, type OfficeActionMode, type OfficeActionsPayload, type OfficeInspectMode, type OfficeInspectPayload } from "./artifactPreviewUtils";

type Setter<T> = (value: T) => void;

function errorText(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function loadOfficeActions(artifact: ToolArtifact, setActionsPayload: Setter<OfficeActionsPayload | null>, setActionsError: Setter<string>) {
  let cancelled = false;
  setActionsPayload(null);
  setActionsError("");
  fetch(officeActionsUrl(artifact), { credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`Action catalog failed (${response.status})`);
      }
      return (await response.json()) as OfficeActionsPayload;
    })
    .then((data) => {
      if (!cancelled) {
        setActionsPayload(data);
      }
    })
    .catch((reason) => {
      if (!cancelled) {
        setActionsError(errorText(reason, "Failed to load Office actions"));
      }
    });
  return () => {
    cancelled = true;
  };
}

function loadOfficeInspect(
  artifact: ToolArtifact,
  mode: OfficeInspectMode,
  setPayload: Setter<OfficeInspectPayload | null>,
  setError: Setter<string>,
) {
  let cancelled = false;
  if (mode === "html") {
    setPayload(null);
    setError("");
    return () => {
      cancelled = true;
    };
  }
  setPayload(null);
  setError("");
  fetch(inspectOfficeUrl(artifact, mode), { credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`Inspect failed (${response.status})`);
      }
      return (await response.json()) as OfficeInspectPayload;
    })
    .then((data) => {
      if (!cancelled) {
        setPayload(data);
      }
    })
    .catch((reason) => {
      if (!cancelled) {
        setError(errorText(reason, "Failed to inspect Office artifact"));
      }
    });
  return () => {
    cancelled = true;
  };
}

export function useOfficeInspectState(artifact: ToolArtifact) {
  const [mode, setMode] = useState<OfficeInspectMode>("html");
  const [actionMode, setActionMode] = useState<OfficeActionMode>("tool_plan");
  const [payload, setPayload] = useState<OfficeInspectPayload | null>(null);
  const [error, setError] = useState("");
  const [actionsPayload, setActionsPayload] =
    useState<OfficeActionsPayload | null>(null);
  const [actionsError, setActionsError] = useState("");
  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  const [showInspector, setShowInspector] = useState(false);
  const [previewHtml, setPreviewHtml] = useState("");

  useEffect(() => {
    setMode("html");
  }, [artifact.path]);
  useEffect(() => loadOfficeActions(artifact, setActionsPayload, setActionsError), [artifact]);
  useEffect(() => loadOfficeInspect(artifact, mode, setPayload, setError), [artifact, mode]);

  const summaryRows = useMemo(() => {
    if (!payload?.summary || typeof payload.summary !== "object") {
      return [];
    }
    return Object.entries(payload.summary).filter(([, value]) => value != null);
  }, [payload]);
  return {
    mode, setMode, actionMode, setActionMode, payload, error, actionsPayload, actionsError, setActionsError,
    busyActionId, setBusyActionId, showInspector, setShowInspector, previewHtml, setPreviewHtml, summaryRows,
  };
}

// The labels of the current inspector mode and the detected file type.
export function officeModeView(
  artifact: ToolArtifact,
  mode: OfficeInspectMode,
  actionMode: OfficeActionMode,
  payload: OfficeInspectPayload | null,
) {
  const isRenderedPreview = mode === "html";
  return {
    detectedFileType: (
      payload?.file_type ||
      artifactExtension(artifact.name).replace(".", "") ||
      "office"
    ).toLowerCase(),
    actionModeDescription:
      actionMode === "tool_plan"
        ? "Tool plan sends a more explicit Office-analysis instruction."
        : "Prompt sends a shorter natural-language request.",
    isRenderedPreview,
    modeTitle: isRenderedPreview
      ? "Document preview"
      : `${mode.charAt(0).toUpperCase()}${mode.slice(1)} view`,
    modeDescription: isRenderedPreview
      ? "This is the document-first view. Use the other tabs only when you need analysis details."
      : "Inspector mode for structured document analysis.",
    showToolbarCopy: !isRenderedPreview,
  };
}

type OfficeActionDraft = {
  artifact: ToolArtifact;
  actionId: string;
  actionMode: OfficeActionMode;
  setBusyActionId: Setter<string | null>;
  setActionsError: Setter<string>;
};

// Resolves an Office action into a draft for the composer.
export async function draftOfficeAction({ artifact, actionId, actionMode, setBusyActionId, setActionsError }: OfficeActionDraft) {
  try {
    setBusyActionId(actionId);
    setActionsError("");
    const resolved = await resolveOfficeAction(artifact, actionId, actionMode);
    window.dispatchEvent(new CustomEvent("octryx:artifact-draft", { detail: resolved.text }));
  } catch (reason) {
    setActionsError(errorText(reason, "Failed to resolve the Office action"));
  } finally {
    setBusyActionId(null);
  }
}

// The rendered document: fetched as HTML for the preview frame; a failed fetch opens the inspector instead.
export function useOfficeRenderedPreview(
  artifactPath: string,
  isRenderedPreview: boolean,
  officePreviewHref: string,
  setPreviewHtml: Setter<string>,
  setShowInspector: Setter<boolean>,
) {
  const [previewState, setPreviewState] = useState<
    "loading" | "ready" | "error"
  >("loading");
  useEffect(() => {
    setPreviewState(isRenderedPreview ? "loading" : "ready");
  }, [artifactPath, isRenderedPreview]);

  useEffect(() => {
    let cancelled = false;
    if (!isRenderedPreview) {
      setPreviewHtml("");
      return undefined;
    }
    setPreviewHtml("");
    fetch(officePreviewHref, { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Preview failed (${response.status})`);
        }
        return response.text();
      })
      .then((html) => {
        if (!cancelled) {
          setPreviewHtml(html);
          setPreviewState("ready");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPreviewState("error");
          setShowInspector(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isRenderedPreview, officePreviewHref, setPreviewHtml, setShowInspector]);
  return previewState;
}
