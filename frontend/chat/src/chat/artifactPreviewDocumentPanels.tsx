// The Office inspect views of a Word document: statistics, text, outline, annotations, form fields and issues.
import {
  formatOfficeValue,
  titleFromKey,
  type OfficeInspectPayload,
} from "./artifactPreviewUtils";

export function documentStatsPanel(payload: OfficeInspectPayload) {
  const rows =
    payload.content && typeof payload.content === "object"
      ? Object.entries(payload.content)
      : [];
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Document statistics</div>
      <div className="artifact-preview__panel-copy">
        Structured document metrics.
      </div>
      <div className="artifact-preview__stat-list">
        {rows.map(([key, value]) => (
          <div key={key} className="artifact-preview__stat-row">
            <span className="artifact-preview__stat-key">
              {titleFromKey(key)}
            </span>
            <span className="artifact-preview__stat-value">
              {formatOfficeValue(value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function documentTextPanel(payload: OfficeInspectPayload) {
  const content = payload.content ?? {};
  const elements = Array.isArray(content.elements) ? content.elements : [];
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">
        Document text outline
      </div>
      <div className="artifact-preview__panel-copy">
        {payload.summary?.total_elements
          ? `${payload.summary.total_elements} elements detected.`
          : "Structured text elements of the document."}
      </div>
      <div className="artifact-preview__list">
        {elements.map((element, index) => {
          const record = element as Record<string, unknown>;
          return (
            <div
              key={`${String(record.path || index)}-${index}`}
              className="artifact-preview__list-item"
            >
              <div className="artifact-preview__list-meta">
                <span>{String(record.type || "element")}</span>
                <span>{String(record.path || "")}</span>
              </div>
              <div className="artifact-preview__list-copy">
                {String(record.text || "").trim() || "(empty)"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function documentOutlinePanel(payload: OfficeInspectPayload) {
  const content = payload.content ?? {};
  const headings = Array.isArray(content.headings) ? content.headings : [];
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Document outline</div>
      <div className="artifact-preview__panel-copy">
        {payload.summary?.headings
          ? `${payload.summary.headings} headings detected.`
          : "Structured heading outline of the document."}
      </div>
      <div className="artifact-preview__list">
        {headings.map((heading, index) => {
          const record = heading as Record<string, unknown>;
          const level = Number(record.level || 1);
          return (
            <div
              key={`${String(record.line || index)}-${index}`}
              className="artifact-preview__list-item"
            >
              <div className="artifact-preview__list-meta">
                <span>{`Level ${level}`}</span>
                <span>{`Line ${String(record.line || "")}`}</span>
                <span>{String(record.style || "heading")}</span>
              </div>
              <div className="artifact-preview__list-copy">
                {String(record.text || "").trim() || "(empty)"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function documentAnnotatedPanel(payload: OfficeInspectPayload) {
  const content = payload.content ?? {};
  const annotatedText =
    typeof content.Content === "string" ? content.Content : "";
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">
        Document annotations
      </div>
      <div className="artifact-preview__panel-copy">
        Annotated text with style and structural metadata.
      </div>
      <pre className="artifact-preview__pre">
        {annotatedText || "No annotated content returned."}
      </pre>
    </div>
  );
}

export function documentFormsPanel(payload: OfficeInspectPayload) {
  const formFields = Array.isArray(payload.content?.fields)
    ? payload.content?.fields
    : [];
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">
        Detected form fields
      </div>
      <div className="artifact-preview__panel-copy">
        Interactive fields found in the document.
      </div>
      <div className="artifact-preview__list">
        {formFields.length ? (
          formFields.map((field, index) => {
            const record = field as Record<string, unknown>;
            return (
              <div
                key={`${String(record.name || index)}-${index}`}
                className="artifact-preview__list-item"
              >
                <div className="artifact-preview__issue-header">
                  <strong>
                    {String(record.name || `Field ${index + 1}`)}
                  </strong>
                </div>
                <div className="artifact-preview__list-meta">
                  <span>{String(record.type || "field")}</span>
                  <span>{String(record.path || "")}</span>
                  <span>{record.required ? "required" : "optional"}</span>
                </div>
              </div>
            );
          })
        ) : (
          <div className="artifact-preview__empty-copy">
            No form fields were detected.
          </div>
        )}
      </div>
    </div>
  );
}

export function documentIssuesPanel(payload: OfficeInspectPayload) {
  const issues = Array.isArray(payload.content?.issues)
    ? payload.content?.issues
    : [];
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Inspect issues</div>
      <div className="artifact-preview__panel-copy">
        Findings of the static document checks.
      </div>
      <div className="artifact-preview__list">
        {issues.length ? (
          issues.map((issue, index) => {
            const record = issue as Record<string, unknown>;
            return (
              <div
                key={`${String(record.code || index)}-${index}`}
                className="artifact-preview__list-item"
              >
                <div className="artifact-preview__issue-header">
                  <strong>{String(record.code || "Issue")}</strong>
                  <span className="artifact-preview__issue-severity">
                    {String(record.severity || "info")}
                  </span>
                </div>
                <div className="artifact-preview__list-copy">
                  {String(record.message || "").trim() || "(no details)"}
                </div>
                <div className="artifact-preview__list-meta">
                  <span>{String(record.path || "")}</span>
                </div>
              </div>
            );
          })
        ) : (
          <div className="artifact-preview__empty-copy">
            No issues reported.
          </div>
        )}
      </div>
    </div>
  );
}
