// Start a run from the Runs tab: choose the open Work item, then the workflow and where it runs (RunStart, the same
// form as on a Work item). The platform checks the Workspace scope first and refuses a device that is not the person's.

import { useEffect, useState } from "react";
import { BottomSheet } from "./BottomSheet";
import { Icon } from "./icons";
import { loadTasks } from "./mobileApi";
import { readCases, stateLabel, type Case } from "./mobileTasksModel";
import { RunStart } from "./RunStart";

export function StartRunSheet({
  workspace,
  workspaces,
  onClose,
  onStarted,
}: {
  workspace: string;
  workspaces: Record<string, string>;
  onClose: () => void;
  onStarted: (runId: string, title: string) => void;
}) {
  const [items, setItems] = useState<Case[] | null>(null);
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<Case | null>(null);
  useEffect(() => {
    let alive = true;
    const timer = window.setTimeout(() => {
      loadTasks({ q: query, limit: 30, project: workspace }).then(
        (raw) => alive && setItems(readCases(raw, null, { keepOrder: true })),
        () => alive && setItems([]),
      );
    }, query ? 300 : 0);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [query, workspace]);

  return (
    <BottomSheet title={chosen ? `Start a run · ${chosen.key}` : "Start a run"} onClose={onClose}>
      {chosen ? (
        <>
          <button type="button" className="m-text-button m-back-link" onClick={() => setChosen(null)}>
            <Icon name="back" size={18} />
            Another Work item
          </button>
          <p className="m-sheet-hint">{chosen.title}</p>
          <RunStart item={chosen} issueType="" onStarted={(runId) => onStarted(runId, `${chosen.key} · ${chosen.title}`)} />
        </>
      ) : (
        <>
          <p className="m-sheet-hint">A run works on one Work item. Choose it first.</p>
          <label className="m-search">
            <Icon name="search" size={18} />
            <input
              type="search"
              aria-label="Search Work items"
              placeholder="Search key or title"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          {items === null && <p className="m-empty">Loading…</p>}
          {items?.length === 0 && <p className="m-empty">No open Work item{query ? ` for “${query}”` : ""}.</p>}
          <ul className="m-rows m-group">
            {(items ?? []).map((item) => (
              <li key={item.id}>
                <button type="button" className="m-row m-row-plain" onClick={() => setChosen(item)}>
                  <span className="m-row-text">
                    <b>
                      {item.key} · {item.title}
                    </b>
                    <span>{[stateLabel(item.state), workspaces[item.projectId]].filter(Boolean).join(" · ")}</span>
                  </span>
                  <Icon name="chevronRight" size={18} className="m-row-chevron" />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </BottomSheet>
  );
}
