import { useState } from "react";

import { excludedWarning, isCommitId } from "./handoffWorkState";
import type { WorkState } from "./handoffWorkState";

// The work state of a handoff in the viewer (root freeze 3c): the WIP branch with a copy-able fetch/checkout
// command, or the bundle download, the base and WIP commits, and the files that stayed on the machine. All values are
// plain text; the command exists only for a safe branch name (handoffWorkState.isSafeBranch).
export function AgentsHandoffWorkState({ state, bundleHref }: { state: WorkState; bundleHref: string | null }) {
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);
  const copy = async () => {
    try {
      const clipboard = (globalThis as { navigator?: { clipboard?: { writeText?: (text: string) => Promise<void> } } }).navigator?.clipboard;
      if (!clipboard?.writeText) throw new Error("no clipboard");
      await clipboard.writeText(state.command);
      setCopied("ok");
    } catch {
      setCopied("failed");
    }
  };
  const commit = (value: string) => (isCommitId(value) ? value.slice(0, 12) : value);

  return (
    <div className="agents-handoff__work-state" data-testid="agents-handoff-work-state">
      <strong>Work state</strong>
      {state.branch ? (
        <p className="agents-board__body" data-testid="agents-handoff-branch">Branch: {state.branch}</p>
      ) : null}
      {state.command ? (
        <div className="agents-board__actions">
          <code className="agents-handoff__command" data-testid="agents-handoff-command">{state.command}</code>
          <button type="button" className="admin-panel__action-btn" onClick={() => void copy()}>Copy command</button>
          {copied ? (
            <span className="agents-area__hint" role="status" data-testid="agents-handoff-copied">
              {copied === "ok" ? "Copied." : "Could not copy; select the command and copy it by hand."}
            </span>
          ) : null}
        </div>
      ) : state.branch ? (
        <p className="agents-area__hint" data-testid="agents-handoff-no-command">The branch name is unusual, so no command is offered; fetch it by hand.</p>
      ) : null}
      {state.bundleId && bundleHref ? (
        <p className="agents-area__hint">
          The work travels as a git bundle on Octryx (<code>octryx-claude resume</code> fetches and verifies it).{" "}
          <a className="admin-panel__action-btn" href={bundleHref} download data-testid="agents-handoff-bundle">Download bundle</a>
        </p>
      ) : null}
      {state.baseCommit || state.wipCommit ? (
        <p className="agents-area__hint" data-testid="agents-handoff-commits"
          title={[state.baseCommit && `Base ${state.baseCommit}`, state.wipCommit && `WIP ${state.wipCommit}`].filter(Boolean).join(" · ")}>
          {state.baseCommit ? `Base ${commit(state.baseCommit)}` : ""}
          {state.baseCommit && state.wipCommit ? " · " : ""}
          {state.wipCommit ? `WIP ${commit(state.wipCommit)}` : ""}
        </p>
      ) : null}
      {state.excludedFiles.length ? (
        <p className="work-area__notice" role="note" data-testid="agents-handoff-excluded">{excludedWarning(state.excludedFiles)}</p>
      ) : null}
    </div>
  );
}
