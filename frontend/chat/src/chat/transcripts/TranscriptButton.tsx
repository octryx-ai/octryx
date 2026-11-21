import { useState } from "react";

import type { TranscriptFilter, TranscriptItem } from "./transcriptModel";
import { TranscriptViewer } from "./TranscriptViewer";
import { useTranscriptItems } from "./useTranscriptItems";

export function TranscriptIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M5.5 3.5h6l3 3v10h-9z" />
      <path d="M11.5 3.5v3h3" />
      <path d="M7.5 10h5M7.5 12.5h5M7.5 15h3" />
    </svg>
  );
}

/** The viewer for `items`, opened by whatever control the page renders. */
export function useTranscriptViewer(items: TranscriptItem[]) {
  const [open, setOpen] = useState(false);
  return {
    available: items.length > 0,
    open: () => setOpen(true),
    viewer: open && items.length ? <TranscriptViewer items={items} onClose={() => setOpen(false)} /> : null,
  };
}

/**
 * A quiet "Transcript" text link that appears only when the session, run or device job has a stored transcript
 * (run details, device job line). Renders nothing otherwise.
 */
export function TranscriptLink({ projectId, filter, testId = "transcript-link" }: {
  projectId: string | null | undefined;
  filter: TranscriptFilter;
  testId?: string;
}) {
  const items = useTranscriptItems(projectId, [filter]);
  const { available, open, viewer } = useTranscriptViewer(items);
  if (!available) return null;
  return (
    <>
      <button type="button" className="ds-link-button transcript-link" data-testid={testId} onClick={open}>
        <TranscriptIcon />
        <span>Transcript</span>
      </button>
      {viewer}
    </>
  );
}
