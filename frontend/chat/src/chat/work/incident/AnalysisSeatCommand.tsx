import { useState } from "react";

// A seat Workspace's analysis (follow-up): the server never starts it; the user runs the command in a terminal,
// in their own Claude subscription (`octryx-claude analyze <KEY>`). Shown instead of the start button.
export function AnalysisSeatCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);
  const copy = async () => {
    try {
      const clipboard = (globalThis as { navigator?: { clipboard?: { writeText?: (text: string) => Promise<void> } } }).navigator?.clipboard;
      if (!clipboard?.writeText) throw new Error("no clipboard");
      await clipboard.writeText(command);
      setCopied("ok");
    } catch {
      setCopied("failed");
    }
  };
  return (
    <div className="work-analysis__seat" data-testid="analysis-seat">
      <span className="work-detail__empty">This Workspace analyses in your own seat session. Run this in a terminal:</span>
      <code className="work-analysis__command" data-testid="analysis-seat-command">{command}</code>
      <button type="button" className="work-area__button" onClick={() => void copy()} data-testid="analysis-seat-copy">
        {copied === "ok" ? "Copied" : "Copy"}
      </button>
      {copied === "failed" ? <span className="work-detail__empty" role="status">Copying is not available here: select the command instead.</span> : null}
    </div>
  );
}
