import { SegmentedTabs } from "../layout/SegmentedTabs";
import {
  type OfficeActionMode,
  type OfficeInspectMode,
  type OfficeInspectPayload,
} from "./artifactPreviewUtils";
import {
  documentAnnotatedPanel,
  documentFormsPanel,
  documentIssuesPanel,
  documentOutlinePanel,
  documentStatsPanel,
  documentTextPanel,
} from "./artifactPreviewDocumentPanels";
import {
  PresentationAnnotatedPanel,
  PresentationOutlinePanel,
  PresentationStatsPanel,
  PresentationTextPanel,
  SpreadsheetAnnotatedPanel,
  SpreadsheetOutlinePanel,
  SpreadsheetStatsPanel,
  SpreadsheetTextPanel,
} from "./artifactPreviewOfficeContentPanels";

export function OfficeModeTabs({
  mode,
  onChange,
  fileType,
}: {
  mode: OfficeInspectMode;
  onChange: (next: OfficeInspectMode) => void;
  fileType: string;
}) {
  const tabs: OfficeInspectMode[] =
    fileType === "docx"
      ? ["html", "text", "outline", "annotated", "stats", "issues", "forms"]
      : ["html", "text", "outline", "annotated", "stats", "issues"];
  const labels: Record<OfficeInspectMode, string> = {
    html: "Preview",
    text: "Text",
    outline: "Outline",
    annotated: "Annotations",
    stats: "Stats",
    issues: "Issues",
    forms: "Forms",
  };
  return (
    <SegmentedTabs label="Office preview modes" idPrefix="office-preview" size="small" value={mode}
      onChange={(key) => onChange(key as OfficeInspectMode)} tabs={tabs.map((tab) => ({ key: tab, label: labels[tab] }))} />
  );
}

export function OfficeActionModeToggle({
  value,
  onChange,
}: {
  value: OfficeActionMode;
  onChange: (next: OfficeActionMode) => void;
}) {
  return (
    <SegmentedTabs label="Office action format" idPrefix="office-action-mode" size="small" value={value}
      onChange={(key) => onChange(key as OfficeActionMode)}
      tabs={[{ key: "prompt", label: "Prompt" }, { key: "tool_plan", label: "Tool plan" }]} />
  );
}

export function OfficeContentPanel({
  payload,
  mode,
  error,
}: {
  payload: OfficeInspectPayload | null;
  mode: Exclude<OfficeInspectMode, "html">;
  error: string;
}) {
  if (error) {
    return (
      <div className="artifact-preview__empty">
        <div className="artifact-preview__empty-title">
          Office inspect failed
        </div>
        <div className="artifact-preview__empty-copy">{error}</div>
      </div>
    );
  }
  if (!payload) {
    return (
      <div className="artifact-preview__empty">
        <div className="artifact-preview__empty-title">
          Loading office details
        </div>
        <div className="artifact-preview__empty-copy">
          Fetching the selected view…
        </div>
      </div>
    );
  }

  if (mode === "stats") {
    if (payload.file_type === "xlsx") {
      return (
        <SpreadsheetStatsPanel
          content={(payload.content ?? {}) as Record<string, unknown>}
        />
      );
    }
    if (payload.file_type === "pptx") {
      return (
        <PresentationStatsPanel
          content={(payload.content ?? {}) as Record<string, unknown>}
        />
      );
    }
    return documentStatsPanel(payload);
  }

  if (mode === "text") {
    const content = payload.content ?? {};
    if (payload.file_type === "xlsx" && Array.isArray(content.sheets)) {
      return <SpreadsheetTextPanel content={content} payload={payload} />;
    }
    if (payload.file_type === "pptx" && Array.isArray(content.slides)) {
      return <PresentationTextPanel content={content} />;
    }
    return documentTextPanel(payload);
  }

  if (mode === "outline") {
    const content = payload.content ?? {};
    if (payload.file_type === "xlsx" && Array.isArray(content.sheets)) {
      return <SpreadsheetOutlinePanel content={content} />;
    }
    if (payload.file_type === "pptx" && Array.isArray(content.slides)) {
      return <PresentationOutlinePanel content={content} payload={payload} />;
    }
    return documentOutlinePanel(payload);
  }

  if (mode === "annotated") {
    const content = payload.content ?? {};
    if (payload.file_type === "xlsx") {
      return <SpreadsheetAnnotatedPanel content={content} />;
    }
    if (payload.file_type === "pptx") {
      return <PresentationAnnotatedPanel content={content} />;
    }
    return documentAnnotatedPanel(payload);
  }

  if (mode === "forms") {
    return documentFormsPanel(payload);
  }

  return documentIssuesPanel(payload);
}
