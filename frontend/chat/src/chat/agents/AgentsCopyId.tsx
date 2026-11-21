import { useState } from "react";

import { shortId } from "./agentBoardLabels";

// A long id (agent key hash, commit, package checksum) shown shortened, with the full value on hover and a copy button.
// When the clipboard is not available the full value stays in the title to select by hand.
export function AgentsCopyId({ value, label = "id", testId }: { value: string; label?: string; testId?: string }) {
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);
  const copy = async () => {
    try {
      const clipboard = (globalThis as { navigator?: { clipboard?: { writeText?: (text: string) => Promise<void> } } }).navigator?.clipboard;
      if (!clipboard?.writeText) throw new Error("no clipboard");
      await clipboard.writeText(value);
      setCopied("ok");
    } catch {
      setCopied("failed");
    }
  };
  const short = shortId(value);
  return (
    <span className="agents-copy-id" data-testid={testId}>
      <code title={value}>{short}</code>
      {short !== value || copied ? (
        <button type="button" className="admin-panel__action-btn" aria-label={`Copy the full ${label}`} onClick={() => void copy()}>
          {copied === "ok" ? "Copied" : copied === "failed" ? "Copy failed" : "Copy"}
        </button>
      ) : null}
    </span>
  );
}
