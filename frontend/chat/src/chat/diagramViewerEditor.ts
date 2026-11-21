// The draw.io side of the diagram viewer: embed address, embed events and opening the full editor in a new tab.
import {
  buildDrawioEditorUrl,
  supportsDrawioEditorUrl,
} from "./drawioEditorUrl";

export type DrawioEventData =
  | { event: "init" }
  | { event: "load"; xml: string }
  | { event: "save"; xml: string }
  | { event: "export"; data: string; format: string; xml: string }
  | { event: "error"; message: string }
  | { event: string };

// Minimal embed URL — per draw.io official embed documentation.
// postMessage must use "*" as targetOrigin (draw.io may use app.diagrams.net internally).
export const EMBED_URL =
  "https://embed.diagrams.net/?embed=1&spin=1&proto=json&ui=atlas";

/** Opens the full draw.io editor for the diagram in a new tab, or the server preview page as the fallback. */
export function openDiagramInFullEditor(diagramId: string | undefined, xml: string) {
  // Server-rendered preview page; carries its own working editor link.
  const previewFallback = diagramId
    ? `/chat/api/artifact-preview?path=${encodeURIComponent(`diagram://${diagramId}`)}`
    : null;
  if (!supportsDrawioEditorUrl()) {
    if (previewFallback) {
      window.open(previewFallback, "_blank", "noopener,noreferrer");
    }
    return;
  }
  // Open the tab synchronously so popup blockers attribute it to the click,
  // then fill in the deep link once the XML is compressed. app.diagrams.net
  // is a trusted target, so keeping the window handle (no noopener) is fine.
  const editorWindow = window.open("about:blank", "_blank");
  buildDrawioEditorUrl(xml)
    .then((url) => {
      if (editorWindow) editorWindow.location.href = url;
    })
    .catch(() => {
      if (editorWindow && previewFallback) {
        editorWindow.location.href = previewFallback;
      } else {
        editorWindow?.close();
      }
    });
}
