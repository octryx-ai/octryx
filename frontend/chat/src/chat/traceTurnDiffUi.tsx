import { normalizeTurnDiff, summarizeTurnDiffEntry, turnDiffBadgeTone } from "./traceTurnDiff";

export function TraceTurnDiffSection({
  turnDiff,
  className = "trace-turn-diff",
  keyPrefix = "trace",
}: {
  turnDiff?: Record<string, unknown> | null;
  className?: string;
  keyPrefix?: string;
}) {
  const { commands, fileChanges, policyEvents } = normalizeTurnDiff(turnDiff);
  if (!commands.length && !fileChanges.length && !policyEvents.length) {
    return null;
  }

  return (
    <section className={className}>
      <div className="trace-turn-diff__header">Execution diff</div>
      {commands.length ? (
        <div className="trace-turn-diff__section trace-turn-diff__section--command">
          <div className="trace-turn-diff__label">Commands</div>
          {commands.map((command, index) => (
            <div
              key={`${keyPrefix}-cmd-${index}`}
              className="trace-turn-diff__item"
            >
              <span className="trace-turn-diff__item-icon" aria-hidden="true">
                {">_"}
              </span>
              <div className="trace-turn-diff__item-copy">
                <strong>{summarizeTurnDiffEntry(command, "command")}</strong>
                {command.cwd ? (
                  <span className="trace-turn-diff__subtle">
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
        </div>
      ) : null}
      {fileChanges.length ? (
        <div className="trace-turn-diff__section trace-turn-diff__section--file">
          <div className="trace-turn-diff__label">File changes</div>
          {fileChanges.map((entry, index) => (
            <div
              key={`${keyPrefix}-file-${index}`}
              className="trace-turn-diff__item"
            >
              <span className="trace-turn-diff__item-icon" aria-hidden="true">
                {"#"}
              </span>
              <div className="trace-turn-diff__item-copy">
                <strong>
                  {String(entry.path || summarizeTurnDiffEntry(entry, "file"))}
                </strong>
                {entry.details ? (
                  <span className="trace-turn-diff__subtle">
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
        </div>
      ) : null}
      {policyEvents.length ? (
        <div className="trace-turn-diff__section trace-turn-diff__section--policy">
          <div className="trace-turn-diff__label">Policy events</div>
          {policyEvents.map((entry, index) => (
            <div
              key={`${keyPrefix}-policy-${index}`}
              className="trace-turn-diff__item"
            >
              <span className="trace-turn-diff__item-icon" aria-hidden="true">
                {"!"}
              </span>
              <div className="trace-turn-diff__item-copy">
                <strong>{summarizeTurnDiffEntry(entry, "policy")}</strong>
                {entry.reason ? (
                  <span className="trace-turn-diff__subtle">
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
        </div>
      ) : null}
    </section>
  );
}
