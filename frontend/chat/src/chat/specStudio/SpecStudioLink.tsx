import { StudioIcon } from "./specStudioIcons";
import { specStudioHref, specStudioLinkText, type SpecStudioSummary } from "./specStudioAddress";

// The run card's way into the Spec Studio (desktop run bar and phone run page), shown once the spec phase recorded
// one. The phone opens the same /chat page: one column, the desktop mock scaled to the width.

export function SpecStudioLink({ runId, summary, className }: { runId: string; summary?: SpecStudioSummary | null; className: string }) {
  if (!summary) return null;
  return (
    <a className={className} href={specStudioHref(runId)} data-testid="spec-studio-link">
      <StudioIcon name="comment" />{specStudioLinkText(summary)}
    </a>
  );
}
