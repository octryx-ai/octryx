import {
  formatOfficeValue,
  titleFromKey,
  type OfficeInspectPayload,
} from "./artifactPreviewUtils";

export function SpreadsheetTextPanel({
  content,
  payload,
}: {
  content: Record<string, unknown>;
  payload: OfficeInspectPayload;
}) {
  const sheets = Array.isArray(content.sheets) ? content.sheets : [];
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Workbook text view</div>
      <div className="artifact-preview__panel-copy">
        {payload.summary?.total_elements
          ? `${payload.summary.total_elements} workbook elements detected.`
          : "Sheet-oriented preview of the workbook."}
      </div>
      <div className="artifact-preview__list">
        {sheets.map((sheet, index) => {
          const record = sheet as Record<string, unknown>;
          const rows = Array.isArray(record.rows) ? record.rows : [];
          return (
            <div
              key={`${String(record.name || index)}-${index}`}
              className="artifact-preview__list-item"
            >
              <div className="artifact-preview__issue-header">
                <strong>{String(record.name || `Sheet ${index + 1}`)}</strong>
              </div>
              <div className="artifact-preview__list">
                {rows.map((row, rowIndex) => {
                  const rowRecord = row as Record<string, unknown>;
                  const cells =
                    rowRecord.cells && typeof rowRecord.cells === "object"
                      ? Object.entries(
                          rowRecord.cells as Record<string, unknown>,
                        )
                      : [];
                  return (
                    <div
                      key={`${String(rowRecord.row || rowIndex)}-${rowIndex}`}
                      className="artifact-preview__list-item"
                    >
                      <div className="artifact-preview__list-meta">
                        <span>{`Row ${String(rowRecord.row || rowIndex + 1)}`}</span>
                      </div>
                      <div className="artifact-preview__list-copy">
                        {cells
                          .map(
                            ([cell, value]) =>
                              `${cell}: ${formatOfficeValue(value)}`,
                          )
                          .join(" | ")}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SpreadsheetStatsPanel({
  content,
}: {
  content: Record<string, unknown>;
}) {
  const rows = Object.entries(content);
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Workbook statistics</div>
      <div className="artifact-preview__panel-copy">
        {content.sheets
          ? `${formatOfficeValue(content.sheets)} sheets analyzed.`
          : "Sheet, cell and formula metrics of the workbook."}
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

export function SpreadsheetOutlinePanel({
  content,
}: {
  content: Record<string, unknown>;
}) {
  const sheets = Array.isArray(content.sheets) ? content.sheets : [];
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Workbook outline</div>
      <div className="artifact-preview__panel-copy">
        Sheet-level structure including row, column and formula counts.
      </div>
      <div className="artifact-preview__list">
        {sheets.map((sheet, index) => {
          const record = sheet as Record<string, unknown>;
          return (
            <div
              key={`${String(record.name || index)}-${index}`}
              className="artifact-preview__list-item"
            >
              <div className="artifact-preview__issue-header">
                <strong>{String(record.name || `Sheet ${index + 1}`)}</strong>
              </div>
              <div className="artifact-preview__list-meta">
                <span>{`Rows: ${formatOfficeValue(record.rows)}`}</span>
                <span>{`Cols: ${formatOfficeValue(record.cols)}`}</span>
                <span>{`Formulas: ${formatOfficeValue(record.formulas)}`}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SpreadsheetAnnotatedPanel({
  content,
}: {
  content: Record<string, unknown>;
}) {
  const annotatedText =
    typeof content.Content === "string" ? content.Content : "";
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Workbook annotations</div>
      <div className="artifact-preview__panel-copy">
        Cell values with type and formula annotations across workbook sheets.
      </div>
      <pre className="artifact-preview__pre">
        {annotatedText || "No annotated workbook content returned."}
      </pre>
    </div>
  );
}

export function PresentationOutlinePanel({
  content,
  payload,
}: {
  content: Record<string, unknown>;
  payload: OfficeInspectPayload;
}) {
  const slides = Array.isArray(content.slides) ? content.slides : [];
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Slide outline</div>
      <div className="artifact-preview__panel-copy">
        {payload.summary?.headings
          ? `${payload.summary.headings} outline items detected.`
          : `Presentation structure${content.totalSlides ? ` across ${formatOfficeValue(content.totalSlides)} slides` : ""}.`}
      </div>
      <div className="artifact-preview__list">
        {slides.map((slide, index) => {
          const record = slide as Record<string, unknown>;
          return (
            <div
              key={`${String(record.index || index)}-${index}`}
              className="artifact-preview__list-item"
            >
              <div className="artifact-preview__issue-header">
                <strong>{`Slide ${String(record.index || index + 1)}`}</strong>
              </div>
              <div className="artifact-preview__list-meta">
                <span>{`Text boxes: ${formatOfficeValue(record.textBoxes)}`}</span>
                <span>{`Pictures: ${formatOfficeValue(record.pictures)}`}</span>
                {record.title ? (
                  <span>{`Title: ${formatOfficeValue(record.title)}`}</span>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function PresentationStatsPanel({
  content,
}: {
  content: Record<string, unknown>;
}) {
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">
        Presentation statistics
      </div>
      <div className="artifact-preview__panel-copy">
        Slide and object metrics of the presentation.
      </div>
      <div className="artifact-preview__stat-list">
        {Object.entries(content).map(([key, value]) => (
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

export function PresentationAnnotatedPanel({
  content,
}: {
  content: Record<string, unknown>;
}) {
  const annotatedText =
    typeof content.Content === "string" ? content.Content : "";
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Slide annotations</div>
      <div className="artifact-preview__panel-copy">
        Slide-scoped text boxes and formatting annotations.
      </div>
      <pre className="artifact-preview__pre">
        {annotatedText || "No annotated slide content returned."}
      </pre>
    </div>
  );
}

export function PresentationTextPanel({
  content,
}: {
  content: Record<string, unknown>;
}) {
  const slides = Array.isArray(content.slides) ? content.slides : [];
  return (
    <div className="artifact-preview__panel">
      <div className="artifact-preview__panel-title">Slide text</div>
      <div className="artifact-preview__panel-copy">
        {content.totalSlides
          ? `${formatOfficeValue(content.totalSlides)} slides extracted.`
          : "Slide-by-slide text of the presentation."}
      </div>
      <div className="artifact-preview__list">
        {slides.map((slide, index) => {
          const record = slide as Record<string, unknown>;
          const texts = Array.isArray(record.texts) ? record.texts : [];
          return (
            <div
              key={`${String(record.index || index)}-${index}`}
              className="artifact-preview__list-item"
            >
              <div className="artifact-preview__issue-header">
                <strong>{`Slide ${String(record.index || index + 1)}`}</strong>
              </div>
              <div className="artifact-preview__list-meta">
                <span>{String(record.path || "")}</span>
              </div>
              <div className="artifact-preview__list">
                {texts.map((text, textIndex) => (
                  <div key={textIndex} className="artifact-preview__list-item">
                    <div className="artifact-preview__list-copy">
                      {String(text || "").trim() || "(empty)"}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
