// The parts of the custom detector drawer: the definition fields, the live test, the save refusals and the footer.
import {
  CHECKS, CONTEXT_WINDOW, CUSTOM_MASK_STYLES, CUSTOM_PREFIX, MAX_PATTERN_CHARS, categoryLabel, detectorConfidence, parseContextWords,
} from "./detectorsModel";
import type { CustomDetector, DetectorCatalog, DetectorIssue, PreviewResult } from "./detectorsModel";
import { NEW_CATEGORY } from "./customDetectorPreview";

// High with a check or keywords, else medium.
function DetectorConfidence({ detector }: { detector: CustomDetector }) {
  const confidence = detectorConfidence(detector);
  return (
    <div className="admin-panel__field"><span>Confidence</span>
      <div data-testid="detector-confidence"><span className={`work-badge work-badge--${confidence === "high" ? "active" : "neutral"}`}>{confidence}</span>{" "}
        <span className="policies__sub">{confidence === "high" ? "pattern + check or keyword" : "pattern only — add a check or keywords for high"}</span></div></div>
  );
}

// Name, id, category (or a new one), scope, pattern, check, keywords, mask and the resulting confidence.
export function DetectorDefinition({ detector, frozen, catalog, workspaces, newCategory, keywords, setKeywords, rename, editId,
  pickCategory, nameCategory, patch }: {
  detector: CustomDetector;
  frozen: boolean;
  catalog: DetectorCatalog;
  workspaces: { id: string; name: string }[];
  newCategory: { id: string; label: string } | null;
  keywords: string;
  setKeywords: (keywords: string) => void;
  rename: (label: string) => void;
  editId: (id: string) => void;
  pickCategory: (value: string) => void;
  nameCategory: (label: string) => void;
  patch: (next: Partial<CustomDetector>) => void;
}) {
  return (
    <fieldset className="detectors__fieldset work-detail__section" disabled={frozen}>
      <h3>Definition</h3>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field"><span>Name</span>
          <input value={detector.label} maxLength={80} placeholder="A name admins recognise" data-testid="detector-name" onChange={(event) => rename(event.target.value)} /></label>
        <label className="admin-panel__field"><span>Id (used in policies)</span>
          <input className="admin-policy-inline-code" value={detector.id} maxLength={47} placeholder={`${CUSTOM_PREFIX}…`} data-testid="detector-id"
            onChange={(event) => editId(event.target.value)} /></label>
        <label className="admin-panel__field"><span>Category</span>
          <select value={newCategory ? NEW_CATEGORY : detector.category} data-testid="detector-category" onChange={(event) => pickCategory(event.target.value)}>
            <option value="">Pick a category</option>
            {catalog.categories.map((item) => <option key={item.id} value={item.id}>{categoryLabel(catalog.categories, item.id)}</option>)}
            <option value={NEW_CATEGORY}>+ New category…</option>
          </select></label>
        <label className="admin-panel__field"><span>Scope</span>
          <select value={detector.workspaceId} data-testid="detector-scope" onChange={(event) => patch({ workspaceId: event.target.value })}>
            <option value="">All Workspaces</option>
            {workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            {detector.workspaceId && !workspaces.some((item) => item.id === detector.workspaceId) ? <option value={detector.workspaceId}>Unknown Workspace {detector.workspaceId}</option> : null}
          </select></label>
        {newCategory ? (
          <label className="admin-panel__field detectors__wide"><span>New category name{newCategory.id ? ` · id ${newCategory.id}` : ""}</span>
            <input value={newCategory.label} maxLength={60} placeholder="A name for the new category" data-testid="detector-new-category"
              onChange={(event) => nameCategory(event.target.value)} /></label>
        ) : null}
        <label className="admin-panel__field detectors__wide"><span>Pattern (RE2, ≤ {MAX_PATTERN_CHARS} characters · {detector.pattern.length})</span>
          <input className="admin-policy-inline-code" value={detector.pattern} maxLength={MAX_PATTERN_CHARS} placeholder="An RE2 regular expression" data-testid="detector-pattern"
            onChange={(event) => patch({ pattern: event.target.value })} /></label>
        <label className="admin-panel__field"><span>Check</span>
          <select value={detector.check} data-testid="detector-check" onChange={(event) => patch({ check: event.target.value })}>
            {CHECKS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
        <label className="admin-panel__field"><span>Only near keywords (optional, ±{CONTEXT_WINDOW} chars)</span>
          <input value={keywords} placeholder="Comma-separated, optional" data-testid="detector-keywords"
            onChange={(event) => { setKeywords(event.target.value); patch({ contextWords: parseContextWords(event.target.value) }); }} /></label>
        <label className="admin-panel__field"><span>Mask as</span>
          <select value={detector.maskStyle} data-testid="detector-mask" onChange={(event) => patch({ maskStyle: event.target.value })}>
            {CUSTOM_MASK_STYLES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
        <DetectorConfidence detector={detector} />
      </div>
    </fieldset>
  );
}

// A sample text, tested against the unsaved definition; the matches and the masked text appear below.
export function DetectorTest({ detector, test, setTest, preview, previewIssue, previewId }: {
  detector: CustomDetector;
  test: string;
  setTest: (test: string) => void;
  preview: PreviewResult | null;
  previewIssue: string | null;
  previewId: string;
}) {
  const matches = preview?.counts[previewId] ?? 0;
  return (
    <section className="work-detail__section">
      <h3>Test</h3>
      <label className="admin-panel__field"><span>Sample text</span>
        <textarea rows={4} value={test} placeholder="Type or paste synthetic sample text" data-testid="detector-test" onChange={(event) => setTest(event.target.value)} /></label>
      {previewIssue ? <p className="workspace-classification__message" role="alert" data-testid="detector-test-problem">{previewIssue}</p> : null}
      {preview ? (
        <div data-testid="detector-test-result">
          <p data-testid="detector-test-counts">{detector.label.trim() || "This detector"}: <b>{matches}</b> match{matches === 1 ? "" : "es"}
            {Object.entries(preview.counts).filter(([id]) => id !== previewId).map(([id, count]) => ` · ${id} ×${count}`).join("")}</p>
          <pre className="policies__code" data-testid="detector-test-masked">{preview.maskedText}</pre>
        </div>
      ) : null}
      <div className="policies__note">Synthetic data only — the test text is never stored.</div>
    </section>
  );
}

export function DetectorRefusals({ problem, issues }: { problem: string | null; issues: DetectorIssue[] }) {
  return (
    <>
      {problem ? <p className="workspace-classification__message" role="alert" data-testid="detector-problem">{problem}</p> : null}
      {issues.length ? (
        <ul className="workspace-classification__message" role="alert" data-testid="detector-issues">
          {issues.map((issue) => <li key={`${issue.detectorId}-${issue.code}`}>{issue.detectorId ? <span className="admin-policy-inline-code">{issue.detectorId}</span> : null} {issue.message || issue.code}</li>)}
        </ul>
      ) : null}
    </>
  );
}

export function DetectorFooter({ original, frozen, busy, usedBy, confirmDelete, blocked, onDelete, onClose, onSave }: {
  original: CustomDetector | null;
  frozen: boolean;
  busy: boolean;
  usedBy: string[];
  confirmDelete: boolean;
  blocked: string | null;
  onDelete: () => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
  <>
    {original ? (
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" data-testid="detector-delete"
        disabled={frozen || busy || usedBy.length > 0} title={usedBy.length ? `Used by ${usedBy.join(", ")}` : undefined}
        onClick={onDelete}>{confirmDelete ? "Confirm delete" : "Delete"}</button>
    ) : null}
    <span className="policies__spacer" />
    <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
    <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="detector-save"
      disabled={busy || Boolean(blocked)} title={blocked ?? undefined} onClick={onSave}>Save to draft</button>
  </>
  );
}
