import { StudioIcon } from "./specStudioIcons";
import { specStudioHref, specStudioLinkText, type SpecStudioSummary } from "./specStudioAddress";

export function SpecStudioLink({ runId, summary, className }: { runId: string; summary?: SpecStudioSummary | null; className: string }) {
  if (!summary) return null;
  return (
    <a className={className} href={specStudioHref(runId)} data-testid="spec-studio-link">
      <StudioIcon name="comment" />{specStudioLinkText(summary)}
    </a>
  );
}
