import { useState } from "react";

import { LoadingState } from "../../../layout/LoadingState";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import type { WorkItem } from "../workItemTypes";
import { assigneeFilterOptions } from "../workPeople";
import { myWorkMessage } from "./myWorkModel";
import type { MyWork } from "./useMyWork";

// My work | All items, and the explicit "You in Jira" choice (myWorkModel.ts). The person picks their Jira account
// from the people the Workspace's items are assigned to; nothing is guessed from e-mail or name.

export function WorkScopeSwitch({ myWork }: { myWork: MyWork }) {
  const { state, scope, setScope, setChanging } = myWork;
  return (
    <div className="work-items__scope" data-testid="work-scope">
      <SegmentedTabs label="Which items" idPrefix="work-scope" value={scope} onChange={(key) => setScope(key as typeof scope)}
        tabs={[{ key: "mine", label: "My work" }, { key: "all", label: "All items" }]} />
      {scope === "mine" && state.kind === "set" ? (
        <span className="work-run-start__hint" data-testid="work-scope-identity">
          {`You in Jira: ${state.identity.displayName}`}{" "}
          <button type="button" className="work-area__button" onClick={() => setChanging(true)}>Change</button>
        </span>
      ) : null}
    </div>
  );
}

/** Shown instead of the items while My work cannot show any: the choice, or why it is not possible here. */
export function WorkMyWorkPanel({ myWork, items }: { myWork: MyWork; items: WorkItem[] }) {
  const { state, busy, choose, clear, retry, setScope, changing, setChanging } = myWork;
  const people = assigneeFilterOptions(items);
  const [accountId, setAccountId] = useState(state.kind === "set" ? state.identity.accountId : "");
  const choosing = state.kind === "unset" || (state.kind === "set" && changing);
  if (state.kind === "loading") return <LoadingState label="your work items" variant="cards" rows={3} />;
  return (
    <div className="work-empty" data-testid="work-my-work">
      <div className="work-empty__eyebrow">My work</div>
      <h2>{choosing ? "Who are you in Jira?" : "My work is not available"}</h2>
      <p>{choosing ? myWorkMessage({ kind: "unset" }) : myWorkMessage(state)}</p>
      {choosing ? (
        people.values.length ? (
          <div className="work-run-start">
            <label className="admin-panel__field">
              <span>You in Jira</span>
              <select className="admin-panel__input" value={accountId} disabled={busy} data-testid="work-my-work-person"
                onChange={(event) => setAccountId(event.target.value)}>
                <option value="">Choose a person</option>
                {people.values.map((value) => (
                  <option key={value} value={value}>{people.labels[value]}</option>
                ))}
              </select>
            </label>
            <div className="work-run-start__actions">
              <button type="button" data-testid="work-my-work-save"
                className={`work-area__button${accountId ? " work-area__button--primary" : ""}`}
                disabled={busy || !accountId} onClick={() => void choose(accountId)}>
                {busy ? "Saving…" : "Use this person"}
              </button>
              {!accountId ? <span className="work-run-start__hint">Choose a person first</span> : null}
              {state.kind === "set" ? (
                <>
                  <button type="button" className="work-area__button" onClick={() => setChanging(false)}>Cancel</button>
                  <button type="button" className="work-area__button" disabled={busy} onClick={() => void clear()}>
                    Forget my choice
                  </button>
                </>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="work-run-start__hint">No item in this Workspace is assigned to anyone yet.</p>
        )
      ) : null}
      <div className="work-empty__actions">
        {state.kind === "error" ? <button type="button" className="work-area__button" onClick={retry}>Try again</button> : null}
        <button type="button" className="work-area__button" onClick={() => setScope("all")}>Show all items</button>
      </div>
    </div>
  );
}
