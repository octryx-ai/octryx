// The live test of an unsaved custom detector: a debounced preview of the sample text, where only the answer to the
// latest request is shown. The sample text is sent per request and never stored.
import { previewDetectors } from "./detectorsApi";
import { previewBody, readDetectorIssues, readPreview } from "./detectorsModel";
import type { CustomDetector, DetectorCategory, PreviewResult } from "./detectorsModel";
import { refusalText } from "./policyEngineVersions";

export const NEW_CATEGORY = "__new__";

type PreviewRun = {
  ticket: { current: number };
  detector: CustomDetector;
  previewId: string;
  test: string;
  categories: DetectorCategory[];
  previewDelay: number;
  setPreview: (preview: PreviewResult | null) => void;
  setPreviewIssue: (issue: string | null) => void;
};

/** Starts one preview request after `previewDelay`; returns the cleanup that cancels its timer. */
export function runDetectorPreview({ ticket, detector, previewId, test, categories, previewDelay, setPreview, setPreviewIssue }: PreviewRun) {
  const request = ++ticket.current;
  if (!test.trim() || !detector.pattern || !detector.category) {
    setPreview(null);
    setPreviewIssue(null);
    return;
  }
  // An unnamed draft still previews: a placeholder id and name stand in until the admin fills them in.
  const candidate = { ...detector, id: previewId, label: detector.label.trim() || "Preview" };
  const timer = setTimeout(() => {
    void previewDetectors(previewBody(candidate, categories, test))
      .then((raw) => { if (request === ticket.current) { setPreview(readPreview(raw)); setPreviewIssue(null); } })
      .catch((error) => {
        if (request !== ticket.current) return;
        const found = readDetectorIssues(error);
        setPreview(null);
        setPreviewIssue(found.length ? found.map((item) => item.message).join(" ") : refusalText(error));
      });
  }, previewDelay);
  return () => clearTimeout(timer);
}
