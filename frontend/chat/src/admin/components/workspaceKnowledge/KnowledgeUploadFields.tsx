import { useState } from "react";
import {
  ACCEPT_ATTRIBUTE,
  acceptedFormatsSummary,
  checkUploadFile,
  formatBytes,
  processingSteps,
} from "./knowledgeUploadPolicy";
import type { ChosenUpload } from "./knowledgeUploadPolicy";
import "./knowledge-upload.css";

// A labelled, styled file picker that refuses unaccepted types and oversized files before upload.
export function KnowledgeFileField({ id, chosen, onChange }: {
  id: string;
  chosen: ChosenUpload | null;
  onChange: (chosen: ChosenUpload | null) => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const pick = (file: File | null) => {
    if (!file) { setProblem(null); onChange(null); return; }
    const check = checkUploadFile(file.name, file.size);
    if (!check.ok) { setProblem(check.reason); onChange(null); return; }
    setProblem(null);
    onChange({ file, format: check.format });
  };
  return (
    <div className="knowledge-upload__file">
      <label htmlFor={id} className="knowledge-upload__label">Document</label>
      <input id={id} type="file" accept={ACCEPT_ATTRIBUTE} className="knowledge-upload__input"
        aria-describedby={`${id}-limits`} onChange={(event) => pick(event.target.files?.[0] ?? null)} />
      {chosen ? (
        <span className="knowledge-upload__chosen">
          {chosen.format.label} · {formatBytes(chosen.file.size)}
        </span>
      ) : null}
      {problem ? <p className="knowledge-upload__problem" role="alert">{problem}</p> : null}
    </div>
  );
}

// Accepted formats and their limits, stated from the backend bounds, as the file field's one helper line (
// re-check). Which extensions each group takes is the line's tooltip; what happens after the upload
// (stored, parsed, indexed) is in the Documents help, here only for assistive technology.
export function KnowledgeUploadGuide({ id, chosen }: { id: string; chosen: ChosenUpload | null }) {
  const groups = acceptedFormatsSummary();
  return (
    <div id={`${id}-limits`} className="knowledge-upload__guide">
      <span className="knowledge-upload__formats" data-testid="knowledge-upload-limits"
        title={groups.map((group) => `${group.kind === "document" ? "PDF, Office and HTML" : "Text"}: ${group.extensions.join(", ")}`).join("\n")}>
        {groups.map((group) => `${group.kind === "document" ? "PDF, Office and HTML" : "Text"} up to ${formatBytes(group.maxBytes)}`).join(" · ")}
      </span>
      <span className="ds-sr-only">{processingSteps(chosen?.format.kind ?? null).join(" ")}</span>
    </div>
  );
}
