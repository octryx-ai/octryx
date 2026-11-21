// Standalone diagram preview page (served by /chat/api/artifact-preview for
// diagram artifacts). Reuses the same DiagramViewer as the inline chat so the
// draw.io embed protocol and editor deep link exist in exactly one place; the
// backend only injects the payload JSON (see web/_helpers/drawio_preview.py).
import React from "react";
import ReactDOM from "react-dom/client";

import { DiagramViewer } from "./DiagramViewer";
import "../styles.css";
import "../styles/diagram-preview-page.css";

interface DiagramPreviewPayload {
  xml?: string;
  title?: string;
  diagram_id?: string;
}

function readPayload(): DiagramPreviewPayload {
  const node = document.getElementById("diagram-preview-payload");
  try {
    return JSON.parse(node?.textContent ?? "null") ?? {};
  } catch {
    return {};
  }
}

const payload = readPayload();
const title = payload.title || "Diagram";
document.title = title;

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <div className="diagram-preview-page">
      {payload.xml ? (
        <DiagramViewer
          xml={payload.xml}
          title={title}
          diagramId={payload.diagram_id || undefined}
        />
      ) : (
        <div className="diagram-preview-page__empty">
          No diagram data. Open this page through a chat diagram artifact.
        </div>
      )}
    </div>
  </React.StrictMode>,
);
