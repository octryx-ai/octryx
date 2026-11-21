// The collapsible execution-diff summary under an answer: counts, a preview and the commands, files and policy rows.
import { normalizeTurnDiff, summarizeTurnDiffEntry, summarizeTurnDiffPreview, turnDiffBadgeTone } from "./traceTurnDiff";

function summarizeFileChanges(fileChanges: Array<Record<string, unknown>>) {
  let positive = 0;
  let negative = 0;
  let neutral = 0;
  for (const entry of fileChanges) {
    const action = String(entry.action || "")
      .trim()
      .toLowerCase();
    if (["created", "added", "updated", "modified"].includes(action)) {
      positive += 1;
    } else if (["deleted", "removed"].includes(action)) {
      negative += 1;
    } else {
      neutral += 1;
    }
  }
  return { positive, negative, neutral };
}

type DiffParts = {
  commands: Array<Record<string, unknown>>;
  fileChanges: Array<Record<string, unknown>>;
  policyEvents: Array<Record<string, unknown>>;
};

function TurnDiffStats({ commands, fileChanges, policyEvents }: DiffParts) {
  const fileSummary = summarizeFileChanges(fileChanges);
  return (
    <div className="turn-diff-summary__stats">
      {fileChanges.length ? (
        <>
          {fileSummary.positive ? (
            <span className="turn-diff-summary__delta turn-diff-summary__delta--positive">
              +{fileSummary.positive}
            </span>
          ) : null}
          {fileSummary.negative ? (
            <span className="turn-diff-summary__delta turn-diff-summary__delta--negative">
              -{fileSummary.negative}
            </span>
          ) : null}
          {fileSummary.neutral ? (
            <span className="turn-diff-summary__delta turn-diff-summary__delta--neutral">
              {fileSummary.neutral} changed
            </span>
          ) : null}
        </>
      ) : null}
      {commands.length ? (
        <span className="turn-diff-summary__meta">
          {commands.length} command{commands.length === 1 ? "" : "s"}
        </span>
      ) : null}
      {policyEvents.length ? (
        <span className="turn-diff-summary__meta">
          {policyEvents.length} policy
        </span>
      ) : null}
    </div>
  );
}

function TurnDiffHeader({ commands, fileChanges, policyEvents }: DiffParts) {
  const previewItems = summarizeTurnDiffPreview(
    commands,
    fileChanges,
    policyEvents,
  );
  return (
    <summary className="turn-diff-summary__header">
      <div className="turn-diff-summary__header-main">
        <div className="turn-diff-summary__headline">
          <span className="turn-diff-summary__eyebrow">Execution trace</span>
          <span className="turn-diff-summary__title">Execution diff</span>
          {previewItems.length ? (
            <span className="turn-diff-summary__preview">
              {previewItems.slice(0, 2).join(" · ")}
              {previewItems.length > 2 ? "..." : ""}
            </span>
          ) : null}
        </div>
        <TurnDiffStats commands={commands} fileChanges={fileChanges} policyEvents={policyEvents} />
      </div>
      <span className="turn-diff-summary__toggle">
        <span className="turn-diff-summary__toggle-copy">Open</span>
        <span className="turn-diff-summary__caret" aria-hidden="true">
          {">"}
        </span>
      </span>
    </summary>
  );
}

function TurnDiffOverview({ commands, fileChanges, policyEvents }: DiffParts) {
  const firstCommand = commands[0];
  const firstFileChange = fileChanges[0];
  const firstPolicyEvent = policyEvents[0];
  return (
    <div className="turn-diff-summary__overview">
      {firstCommand ? (
        <div className="turn-diff-summary__overview-item">
          <span className="turn-diff-summary__overview-label">Command</span>
          <span className="turn-diff-summary__overview-copy">
            {summarizeTurnDiffEntry(firstCommand, "command")}
          </span>
        </div>
      ) : null}
      {firstFileChange ? (
        <div className="turn-diff-summary__overview-item">
          <span className="turn-diff-summary__overview-label">File</span>
          <span className="turn-diff-summary__overview-copy">
            {summarizeTurnDiffEntry(firstFileChange, "file")}
          </span>
        </div>
      ) : null}
      {firstPolicyEvent ? (
        <div className="turn-diff-summary__overview-item">
          <span className="turn-diff-summary__overview-label">Policy</span>
          <span className="turn-diff-summary__overview-copy">
            {summarizeTurnDiffEntry(firstPolicyEvent, "policy")}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function TurnDiffCommands({ commands }: { commands: Array<Record<string, unknown>> }) {
  return (
    <section className="turn-diff-summary__section">
      <div className="turn-diff-summary__section-label">Commands</div>
      {commands.map((command, index) => (
        <div
          key={`diff-command-${index}`}
          className="turn-diff-summary__row"
        >
          <div className="turn-diff-summary__row-main">
            <strong>{summarizeTurnDiffEntry(command, "command")}</strong>
            {command.cwd ? (
              <span className="turn-diff-summary__row-subtle">
                cwd {String(command.cwd)}
              </span>
            ) : null}
          </div>
          <span
            className={`trace-turn-diff__badge trace-turn-diff__badge--${turnDiffBadgeTone(
              String(command.status || ""),
            )}`}
          >
            {String(command.status || "command")}
          </span>
        </div>
      ))}
    </section>
  );
}

function TurnDiffFiles({ fileChanges }: { fileChanges: Array<Record<string, unknown>> }) {
  return (
    <section className="turn-diff-summary__section">
      <div className="turn-diff-summary__section-label">Files</div>
      {fileChanges.map((entry, index) => (
        <div
          key={`diff-file-${index}`}
          className="turn-diff-summary__row"
        >
          <div className="turn-diff-summary__row-main">
            <strong>
              {String(
                entry.path || summarizeTurnDiffEntry(entry, "file"),
              )}
            </strong>
            {entry.details ? (
              <span className="turn-diff-summary__row-subtle">
                {String(entry.details)}
              </span>
            ) : null}
          </div>
          <span
            className={`trace-turn-diff__badge trace-turn-diff__badge--${turnDiffBadgeTone(
              String(entry.action || ""),
            )}`}
          >
            {String(entry.action || "change")}
          </span>
        </div>
      ))}
    </section>
  );
}

function TurnDiffPolicy({ policyEvents }: { policyEvents: Array<Record<string, unknown>> }) {
  return (
    <section className="turn-diff-summary__section">
      <div className="turn-diff-summary__section-label">Policy</div>
      {policyEvents.map((entry, index) => (
        <div
          key={`diff-policy-${index}`}
          className="turn-diff-summary__row"
        >
          <div className="turn-diff-summary__row-main">
            <strong>{summarizeTurnDiffEntry(entry, "policy")}</strong>
            {entry.reason ? (
              <span className="turn-diff-summary__row-subtle">
                {String(entry.reason)}
              </span>
            ) : null}
          </div>
          <span
            className={`trace-turn-diff__badge trace-turn-diff__badge--${turnDiffBadgeTone(
              String(entry.action || ""),
            )}`}
          >
            {String(entry.action || "policy")}
          </span>
        </div>
      ))}
    </section>
  );
}

export function TurnDiffSummary({
  turnDiff,
  onOpen,
}: {
  turnDiff?: Record<string, unknown> | null;
  onOpen?: () => void;
}) {
  const { commands, fileChanges, policyEvents } = normalizeTurnDiff(turnDiff);
  if (!commands.length && !fileChanges.length && !policyEvents.length) {
    return null;
  }

  return (
    <details className="turn-diff-summary">
      <TurnDiffHeader commands={commands} fileChanges={fileChanges} policyEvents={policyEvents} />
      <div className="turn-diff-summary__body">
        <TurnDiffOverview commands={commands} fileChanges={fileChanges} policyEvents={policyEvents} />
        {commands.length ? <TurnDiffCommands commands={commands} /> : null}
        {fileChanges.length ? <TurnDiffFiles fileChanges={fileChanges} /> : null}
        {policyEvents.length ? <TurnDiffPolicy policyEvents={policyEvents} /> : null}
        {onOpen ? (
          <div className="turn-diff-summary__footer">
            <button
              type="button"
              className="turn-diff-summary__open"
              onClick={onOpen}
            >
              Open trace
            </button>
          </div>
        ) : null}
      </div>
    </details>
  );
}
