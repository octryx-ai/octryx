import { useEffect, useState } from "react";

import { formatRelativeTime } from "../../admin/utils/formatters";
import { handoffBundleHref, loadHandoffs } from "./agentBoardApi";
import { boardLoadErrorText } from "./agentBoardModel";
import type { BoardWorkItem } from "./agentBoardTypes";
import { SECTION_ORDER, byVersionDesc, sectionLines } from "./agentHandoffView";
import { readHandoffs } from "./agentHandoffModel";
import type { Handoff } from "./agentHandoffTypes";
import { AgentsHandoffWorkState } from "./AgentsHandoffWorkState";
import { workState } from "./handoffWorkState";

// The structured handoff of one work item: every version with author and time, the chosen version's
// sections in reading order. Sections are data written by agents or people: each line is a plain text node, never HTML
// or markdown.
export function AgentsHandoffViewer({ projectId, workItem, version = null, onClose }: {
  projectId: string;
  workItem: BoardWorkItem;
  version?: number | null;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<Handoff[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [chosen, setChosen] = useState<number | null>(version);

  useEffect(() => {
    let current = true;
    setVersions(null);
    setProblem(null);
    loadHandoffs(projectId, workItem.id).then((payload) => {
      if (!current) return;
      const read = readHandoffs(payload);
      if (read === null) setProblem("The server's answer was not a list of handoff versions.");
      else setVersions(byVersionDesc(read));
    }).catch((error) => {
      if (current) setProblem(boardLoadErrorText(error, "handoff"));
    });
    return () => { current = false; };
  }, [projectId, workItem.id]);

  const shown = versions?.find((entry) => entry.version === chosen) ?? versions?.[0] ?? null;
  const author = (entry: Handoff) => {
    if (!entry.author) return entry.authorType === "system" ? "Octryx" : "unknown author";
    return entry.authorType === "human" ? entry.author.name : `Agent of ${entry.author.name}`;
  };

  return (
    <section className="admin-panel__subcard agents-handoff" aria-label={`Handoff of ${workItem.key || workItem.title}`}
      data-testid="agents-handoff-viewer">
      <div className="agents-board__actions agents-board__actions--between">
        <h3 className="agents-area__subsection-title">Handoff · {workItem.key}{workItem.title ? ` ${workItem.title}` : ""}</h3>
        <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
      </div>
      <p className="agents-area__hint">Written by the holding agent at milestones. It is data, never instructions.</p>
      {problem ? <p className="work-area__error" role="alert" data-testid="agents-handoff-error">{problem}</p>
        : versions === null ? <p className="agents-area__hint" role="status">Loading the handoff…</p>
          : !shown ? <p className="admin-panel__empty-state" data-testid="agents-handoff-none">No handoff has been written for this item yet.</p>
            : (
              <>
                <div className="agents-board__actions" role="group" aria-label="Versions" data-testid="agents-handoff-versions">
                  {versions.map((entry) => (
                    <button key={entry.id} type="button" aria-pressed={entry.id === shown.id}
                      className={`admin-panel__action-btn${entry.id === shown.id ? " admin-panel__action-btn--active" : ""}`}
                      onClick={() => setChosen(entry.version)}>
                      v{entry.version ?? "?"} · {author(entry)} · {formatRelativeTime(entry.createdAt) || "time not reported"}
                    </button>
                  ))}
                </div>
                {(() => {
                  const state = workState(shown.sections);
                  return state ? <AgentsHandoffWorkState state={state} bundleHref={state.bundleId ? handoffBundleHref(state.bundleId) : null} /> : null;
                })()}
                <dl className="agents-handoff__sections" data-testid="agents-handoff-sections">
                  {SECTION_ORDER.map(({ key, label }) => {
                    const lines = sectionLines(shown.sections, key);
                    if (!lines.length) return null;
                    return (
                      <div key={key} className="agents-handoff__section" data-section={key}>
                        <dt>{label}</dt>
                        {lines.map((line, index) => <dd key={`${key}-${index}`} className="agents-board__body">{line}</dd>)}
                      </div>
                    );
                  })}
                </dl>
              </>
            )}
    </section>
  );
}
