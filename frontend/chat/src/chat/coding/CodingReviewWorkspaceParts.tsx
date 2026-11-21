// Parts of the file review workspace: the file and event list, the editor, the feedback context and the form.
import type { Dispatch, SetStateAction } from "react";
import { DiffEditor, Editor } from "@monaco-editor/react";

import type { WorkAgentFeedbackContext, WorkCodingReviewEvent, WorkCodingReviewEventType } from "../work/workCodingReviewTypes";
import type { WorkChangeUnit } from "../work/workPullRequestTypes";
import type { CodingSessionSummary } from "./codingTypes";
import { EVENT_TYPES, labelForEvent, languageForPath, type ReviewFormState } from "./codingReviewWorkspaceModel";

type FileListProps = {
  files: string[];
  events: WorkCodingReviewEvent[];
  fileEvents: WorkCodingReviewEvent[];
  selectedFile: string;
  setSelectedFile: (filePath: string) => void;
};

export function ReviewFileList({ files, events, fileEvents, selectedFile, setSelectedFile }: FileListProps) {
  return (
    <aside className="coding-review__files" aria-label="Review files">
      <div className="coding-review__section-heading">
        <span>Files</span>
        <strong>{files.length}</strong>
      </div>
      <div className="coding-review__file-list">
        {files.map((filePath) => {
          const count = events.filter((event) => event.file_path === filePath).length;
          return (
            <button
              key={filePath}
              type="button"
              className={filePath === selectedFile ? "is-active" : ""}
              onClick={() => setSelectedFile(filePath)}
            >
              <span>{filePath}</span>
              <small>{count ? `${count} events` : "ready"}</small>
            </button>
          );
        })}
      </div>
      <div className="coding-review__event-list">
        <div className="coding-review__section-heading">
          <span>Review events</span>
          <strong>{fileEvents.length}</strong>
        </div>
        {fileEvents.length === 0 ? <p>No review feedback captured for this file.</p> : null}
        {fileEvents.map((event) => (
          <article key={event.id} className={`coding-review__event is-${event.event_type}`}>
            <div>
              <strong>{labelForEvent(event.event_type)}</strong>
              <small>
                {event.line_number ? `line ${event.line_number}` : "file"} · {event.severity || "info"}
              </small>
            </div>
            <p>{event.body}</p>
          </article>
        ))}
      </div>
    </aside>
  );
}

type EditorProps = {
  session: CodingSessionSummary;
  selectedFile: string;
  selectedChangeUnit: WorkChangeUnit | undefined;
  latestHumanEdit: WorkCodingReviewEvent | undefined;
  manualEdit: boolean;
  editorContent: string;
  modifiedContent: string;
};

export function ReviewEditor({ session, selectedFile, selectedChangeUnit, latestHumanEdit, manualEdit, editorContent, modifiedContent }: EditorProps) {
  return (
    <main className="coding-review__editor" aria-label="Review editor">
      <div className="coding-review__editor-toolbar">
        <div>
          <strong>{selectedFile}</strong>
          <small>
            {selectedChangeUnit?.repository_name || session.repositories[0] || "Repository pending"} ·{" "}
            {selectedChangeUnit?.branch_name || session.branches[0] || "Branch pending"}
          </small>
        </div>
        <span className="work-badge">{latestHumanEdit ? "human edit visible" : "read only context"}</span>
      </div>
      {latestHumanEdit || manualEdit ? (
        <DiffEditor
          height="33rem"
          language={languageForPath(selectedFile)}
          original={editorContent}
          modified={modifiedContent}
          theme="vs-dark"
          options={{ readOnly: true, minimap: { enabled: false }, renderSideBySide: true, wordWrap: "on" }}
        />
      ) : (
        <Editor
          height="33rem"
          language={languageForPath(selectedFile)}
          value={editorContent}
          theme="vs-dark"
          options={{ readOnly: true, minimap: { enabled: false }, wordWrap: "on" }}
        />
      )}
    </main>
  );
}

export function ReviewFeedbackContext({ feedbackContext }: { feedbackContext: WorkAgentFeedbackContext }) {
  return (
    <section className="coding-review__context">
      <div className="coding-review__section-heading">
        <span>Agent feedback context</span>
        <strong>{feedbackContext.event_count}</strong>
      </div>
      <p>{feedbackContext.agent_instruction}</p>
      <dl>
        <dt>Human edits</dt>
        <dd>{feedbackContext.counts.manual_edit || 0}</dd>
        <dt>Comments</dt>
        <dd>{feedbackContext.counts.inline_comment || 0}</dd>
        <dt>Diagnostics</dt>
        <dd>{feedbackContext.counts.diagnostic || 0}</dd>
      </dl>
      {feedbackContext.constraints.length > 0 ? (
        <ul>
          {feedbackContext.constraints.map((constraint) => (
            <li key={constraint}>{constraint}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

type FormProps = {
  form: ReviewFormState;
  setForm: Dispatch<SetStateAction<ReviewFormState>>;
  saving: boolean;
  error: string | null;
  canSave: boolean;
  onSave: () => void;
};

function EventTypeOptions() {
  return (
    <>
      {EVENT_TYPES.map((eventType) => (
        <option key={eventType.value} value={eventType.value}>
          {eventType.label}
        </option>
      ))}
    </>
  );
}

function SeverityOptions() {
  return (
    <>
      {["info", "low", "medium", "high", "critical"].map((severity) => (
        <option key={severity} value={severity}>
          {severity}
        </option>
      ))}
    </>
  );
}

export function ReviewFeedbackForm({ form, setForm, saving, error, canSave, onSave }: FormProps) {
  return (
    <section className="coding-review__form">
      <div className="coding-review__section-heading">
        <span>Capture feedback</span>
        <strong>{saving ? "saving" : "ready"}</strong>
      </div>
      <label>
        Type
        <select
          value={form.eventType}
          onChange={(event) => setForm((current) => ({ ...current, eventType: event.target.value as WorkCodingReviewEventType }))}
        >
          <EventTypeOptions />
        </select>
      </label>
      <label>
        Severity
        <select
          value={form.severity || "info"}
          onChange={(event) => setForm((current) => ({ ...current, severity: event.target.value as ReviewFormState["severity"] }))}
        >
          <SeverityOptions />
        </select>
      </label>
      <label>
        Line
        <input
          inputMode="numeric"
          value={form.lineNumber}
          onChange={(event) => setForm((current) => ({ ...current, lineNumber: event.target.value }))}
          placeholder="Optional"
        />
      </label>
      <label>
        Feedback
        <textarea
          value={form.body}
          onChange={(event) => setForm((current) => ({ ...current, body: event.target.value }))}
          placeholder="What should the agent change, preserve, or explain?"
        />
      </label>
      {form.eventType === "manual_edit" ? (
        <label>
          Human edit
          <textarea
            value={form.updatedContent}
            onChange={(event) => setForm((current) => ({ ...current, updatedContent: event.target.value }))}
            placeholder="Paste the reviewer-approved replacement content."
          />
        </label>
      ) : null}
      {error ? <p className="coding-review__error">{error}</p> : null}
      <button type="button" onClick={onSave} disabled={!canSave || saving}>
        Save feedback
      </button>
    </section>
  );
}
