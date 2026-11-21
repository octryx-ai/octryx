import type { CodingWorkAction, ListedEntries } from "./codingWorkActionModel";

// The guided Coding-to-Work handoff: why coding cannot continue, and the exact place in
// Work that resolves it. Built only from `codingWorkAction`; it never approves, edits or starts.
export function CodingWorkActionPanel({ action }: { action: CodingWorkAction }) {
  if (action.state === "hidden") return null;
  if (action.state === "checking") {
    return (
      <section className="coding-execution-notice coding-work-action" aria-label="Work action" aria-busy="true">
        <div>
          <strong>{action.title}</strong>
          <span>{action.message}</span>
        </div>
      </section>
    );
  }
  return (
    <section className="coding-execution-notice coding-work-action" aria-label="Work action">
      <div>
        <strong>{action.title}</strong>
        <span>{action.message}</span>
        <EntryList label="Open questions on the plan" entries={action.questions} />
        <EntryList
          label={action.state === "plan" ? "Other recorded blockers (not resolved by the plan)" : "Recorded blockers"}
          entries={action.blockers}
        />
        <span>{action.startHint}</span>
      </div>
      <div className="coding-execution-notice__actions">
        {action.planAction ? (
          <a className="work-area__button work-area__button--primary" href={action.planAction.href}>
            {action.planAction.label}
          </a>
        ) : (
          <a className="work-area__button work-area__button--primary" href={action.workItemHref}>
            Open Work Item
          </a>
        )}
      </div>
    </section>
  );
}

function EntryList({ label, entries }: { label: string; entries: ListedEntries }) {
  if (!entries.shown.length && !entries.unreadable) return null;
  return (
    <div aria-label={label}>
      <span>{label}</span>
      {entries.shown.length ? (
        <ul>
          {entries.shown.map((entry) => (
            <li key={entry}>{entry}</li>
          ))}
        </ul>
      ) : null}
      {entries.more ? <span>{`and ${entries.more} more`}</span> : null}
      {entries.unreadable ? (
        <span>{`${entries.unreadable} recorded ${entries.unreadable === 1 ? "entry has" : "entries have"} no readable text`}</span>
      ) : null}
    </div>
  );
}
