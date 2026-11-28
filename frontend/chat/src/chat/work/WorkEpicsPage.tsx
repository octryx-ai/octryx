import { useEffect, useMemo, useState } from "react";

import { LoadingState } from "../../layout/LoadingState";
import { StatusLabel } from "../../layout/StatusLabel";
import { readJson } from "../chatApiClient";
import {
  barSegments,
  checksLabel,
  checksTone,
  chooseEpic,
  epicProgressPath,
  epicsOf,
  laneLabel,
  laneTone,
  needsYouText,
  plural,
  readEpicProgress,
  reasonText,
  tasksDoneText,
  type EpicProgress,
  type EpicProgressRow,
  type EpicProgressStory,
  type EpicProgressSummary,
} from "./epicViewModel";
import { loadWorkItem } from "./workPlanListApi";
import type { WorkItem } from "./workItemTypes";

type WorkEpicsPageProps = {
  items: WorkItem[];
  reloadKey?: string | number;
  onOpenItem: (item: WorkItem) => void;
};

const EPIC_PARAM = "epic";

function addressedEpic(): string | null {
  return typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get(EPIC_PARAM);
}

function writeEpic(key: string) {
  if (typeof window === "undefined" || !window.location.href) return;
  const next = new URL(window.location.href);
  next.searchParams.set(EPIC_PARAM, key);
  if (next.toString() !== window.location.href) window.history.replaceState(window.history.state, "", next.toString());
}

// Work › Epics: the selected Epic's lanes as the backend derives them from recorded events.
export function WorkEpicsPage({ items, reloadKey, onOpenItem }: WorkEpicsPageProps) {
  const epics = useMemo(() => epicsOf(items), [items]);
  const [wanted, setWanted] = useState<string | null>(addressedEpic);
  const epic = chooseEpic(epics, wanted);
  const epicId = epic?.id ?? "";
  const [progress, setProgress] = useState<EpicProgress | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (epic?.source_key) writeEpic(epic.source_key);
  }, [epic?.source_key]);

  useEffect(() => {
    if (!epicId) return undefined;
    let cancelled = false;
    setError("");
    setProgress(null);
    readJson<unknown>(epicProgressPath(epicId))
      .then((payload) => { if (!cancelled) setProgress(readEpicProgress(payload)); })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error && reason.message ? reason.message : "The epic could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, [epicId, reloadKey, attempt]);

  const openRow = (row: EpicProgressRow) => {
    const known = items.find((item) => item.id === row.id);
    if (known) onOpenItem(known);
    else void loadWorkItem(row.id).then(onOpenItem).catch(() => setError(`${row.key || "The item"} could not be opened.`));
  };

  if (!epic) {
    return (
      <div className="work-empty" data-testid="work-epics-empty">
        <div className="work-empty__eyebrow">Epics</div>
        <h2>No epics yet</h2>
        <p>An epic and its stories show here once a Work Plan or Jira creates them.</p>
      </div>
    );
  }

  const retry = () => setAttempt((value) => value + 1);
  const sourceUrl = progress?.epic.url || epic.source_url;

  return (
    <div className="work-epics" data-testid="work-epics">
      <section className="work-epics__epic" aria-label="Epic">
        <div className="work-epics__epic-head">
          <span className="work-epics__epic-title">
            <span className="work-epics__eyebrow">
              Epic
              {sourceUrl ? <> · <a href={sourceUrl} target="_blank" rel="noreferrer">Open the source</a></> : null}
            </span>
            <span className="work-epics__epic-name">{epic.source_key} · {progress?.epic.title || epic.title}</span>
          </span>
          {epics.length > 1 ? (
            <select className="admin-panel__input work-epics__switch" aria-label="Switch epic" value={epic.source_key}
              onChange={(event) => setWanted(event.target.value)}>
              {epics.map((entry) => <option key={entry.id} value={entry.source_key}>{entry.source_key} · {entry.title}</option>)}
            </select>
          ) : null}
        </div>
        {progress ? <EpicBar summary={progress.summary} /> : null}
      </section>

      {error ? (
        <div className="work-area__error" role="alert">
          {error} <button type="button" className="work-area__button" onClick={retry}>Try again</button>
        </div>
      ) : !progress ? (
        <LoadingState label="epic" rows={5} onRetry={retry} />
      ) : progress.stories.length === 0 ? (
        <p className="work-epics__note">This epic has no stories yet.</p>
      ) : (
        <section className="work-epics__stories" aria-label="Stories">
          {progress.stories.map((story) => <StoryRow key={story.id} story={story} onOpen={openRow} />)}
        </section>
      )}

      <p className="work-epics__note">
        Lanes are set by the platform from recorded events (runs, pull requests, checks, merges), never from what the
        model says.
      </p>
    </div>
  );
}

function EpicBar({ summary }: { summary: EpicProgressSummary }) {
  const segments = barSegments(summary);
  const needsYou = needsYouText(summary);
  return (
    <div className="work-epics__progress" data-testid="work-epics-counts">
      <span className="work-epics__lanes" role="img" aria-label={segments.map((s) => `${s.count} ${s.label}`).join(", ")}>
        {segments.map((s) => <span key={s.lane} className={`work-epics__lane work-epics__lane--${s.lane}`} style={{ width: `${s.share}%` }} />)}
      </span>
      <span className="work-epics__counts">
        {segments.map((s) => (
          <span key={s.lane}><i className={`work-epics__key work-epics__lane--${s.lane}`} aria-hidden="true" /><strong>{s.count}</strong> {s.label}</span>
        ))}
        <span>{summary.total} {plural(summary.total, "story", "stories")}</span>
        {needsYou ? <span><strong className="work-epics__count--attention">{needsYou}</strong></span> : null}
      </span>
    </div>
  );
}

// The pull request link already says "open" or "merged"; the reason would repeat it.
const PULL_REQUEST_REASONS = new Set(["pull request open", "merged"]);

function RowLine({ row, onOpen }: { row: EpicProgressRow; onOpen: (row: EpicProgressRow) => void }) {
  const reason = row.pullRequest && PULL_REQUEST_REASONS.has(row.reason) ? "" : reasonText(row.reason);
  const phase = row.runPhase && reasonText(row.runPhase) !== reason ? reasonText(row.runPhase) : "";
  return (
    <span className="work-epics__row">
      <button type="button" className="work-epics__row-name" onClick={() => onOpen(row)}>{row.key} · {row.title}</button>
      <StatusLabel label={laneLabel(row.lane)} tone={laneTone(row.lane)} />
      {row.needsYou ? <StatusLabel label="Needs you" tone="attention" /> : null}
      {row.checks ? <StatusLabel label={checksLabel(row.checks)} tone={checksTone(row.checks)} /> : null}
      <span className="work-epics__reason">{[reason, phase && `Run: ${phase}`].filter(Boolean).join(" · ")}</span>
      {row.pullRequest ? (
        <span className="work-epics__pr">
          {row.pullRequest.url
            ? <a href={row.pullRequest.url} target="_blank" rel="noreferrer">Pull request</a>
            : "Pull request"}
          {row.pullRequest.status ? ` (${reasonText(row.pullRequest.status).toLowerCase()})` : ""}
        </span>
      ) : null}
    </span>
  );
}

function StoryRow({ story, onOpen }: { story: EpicProgressStory; onOpen: (row: EpicProgressRow) => void }) {
  const done = tasksDoneText(story);
  return (
    <div className="work-epics__story" data-testid="work-epics-story" data-lane={story.lane}>
      <RowLine row={story} onOpen={onOpen} />
      {done ? <span className="work-epics__story-progress">{done}</span> : null}
      {story.tasks.length ? (
        <ul className="work-epics__tasks">
          {story.tasks.map((task) => <li key={task.id} data-testid="work-epics-task"><RowLine row={task} onOpen={onOpen} /></li>)}
        </ul>
      ) : null}
    </div>
  );
}
