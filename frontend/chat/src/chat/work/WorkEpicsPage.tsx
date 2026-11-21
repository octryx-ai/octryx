import { useEffect, useMemo, useState } from "react";

import { LoadingState } from "../../layout/LoadingState";
import { StatusLabel } from "../../layout/StatusLabel";
import { readJson } from "../chatApiClient";
import { hasSeat, SEAT_LABELS, seatAmountText, seatShort, seatSentence } from "../cost/seatEquivalent";
import { TaskList } from "../workflowRun/TaskList";
import { chatSessionHref } from "../workflowRun/workflowRunModel";
import "../workflowRun/workflowRun.css";
import {
  chooseEpic,
  decisionRun,
  epicsOf,
  epicSummary,
  initiallyOpen,
  plural,
  progressShares,
  runsByItem,
  storiesOf,
  storyCost,
  storyProgress,
  storySeat,
  storyPullRequest,
  storyStatus,
  type EpicRun,
  type EpicStory,
} from "./epicViewModel";
import { loadWorkItem } from "./workPlanListApi";
import { costText, workRunsPath } from "./workRunsModel";
import type { WorkItem } from "./workItemTypes";

type WorkEpicsPageProps = {
  items: WorkItem[];
  projectId?: string | null;
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

// Work › Epics (the agreed mock "Work: epic, stories, tasks"): the epic's counts, then each story as a
// foldable row with its task bar, status, pull request and cost; open, the story shows its tasks (TaskList).
export function WorkEpicsPage({ items, projectId, reloadKey, onOpenItem }: WorkEpicsPageProps) {
  const epics = useMemo(() => epicsOf(items), [items]);
  const [wanted, setWanted] = useState<string | null>(addressedEpic);
  const epic = chooseEpic(epics, wanted);
  const epicKey = epic?.source_key ?? "";
  const storyRows = useMemo(() => storiesOf(items, epicKey), [items, epicKey]);
  const storyIds = storyRows.map((row) => row.id).join(",");
  const [details, setDetails] = useState<Record<string, WorkItem>>({});
  const [runs, setRuns] = useState<EpicRun[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (epicKey) writeEpic(epicKey);
  }, [epicKey]);

  useEffect(() => {
    let cancelled = false;
    setError("");
    setRuns(null);
    const ids = storyIds ? storyIds.split(",") : [];
    // The list rows are lean: the tasks are on each story's detail read. A story that cannot be read keeps its row.
    const reads = ids.map((id) => loadWorkItem(id).catch(() => null));
    const runRead = readJson<{ runs: EpicRun[] }>(workRunsPath(projectId)).then((payload) => payload.runs || []);
    void Promise.all([runRead, Promise.all(reads)])
      .then(([nextRuns, full]) => {
        if (cancelled) return;
        setRuns(nextRuns);
        setDetails(Object.fromEntries(full.filter((item): item is WorkItem => Boolean(item)).map((item) => [item.id, item])));
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setRuns([]);
        setError(reason instanceof Error ? reason.message : "The epic could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, [storyIds, projectId, reloadKey, attempt]);

  const stories: EpicStory[] = useMemo(() => {
    const byItem = runsByItem(runs ?? []);
    return storyRows.map((row) => {
      const item = details[row.id] ? { ...row, ...details[row.id] } : row;
      return { item, tasks: item.task_list ?? [], runs: byItem.get(row.id) ?? [] };
    });
  }, [storyRows, details, runs]);

  if (!epic) {
    return (
      <div className="work-empty" data-testid="work-epics-empty">
        <div className="work-empty__eyebrow">Epics</div>
        <h2>No epics yet</h2>
        <p>An epic and its stories show here once a Work Plan or Jira creates them.</p>
      </div>
    );
  }

  if (runs === null) return <LoadingState label="epic" rows={5} onRetry={() => setAttempt((value) => value + 1)} />;

  const summary = epicSummary(stories);
  const openId = initiallyOpen(stories);

  return (
    <div className="work-epics" data-testid="work-epics">
      {error ? <div className="work-area__error">{error}</div> : null}

      <section className="work-epics__epic" aria-label="Epic">
        <div className="work-epics__epic-head">
          <span className="work-epics__epic-title">
            <span className="work-epics__eyebrow">
              Epic
              {epic.source_url ? <> · <a href={epic.source_url} target="_blank" rel="noreferrer">Open the source</a></> : null}
            </span>
            <span className="work-epics__epic-name">{epic.source_key} · {epic.title}</span>
          </span>
          {epics.length > 1 ? (
            <select className="admin-panel__input work-epics__switch" aria-label="Switch epic" value={epic.source_key}
              onChange={(event) => setWanted(event.target.value)}>
              {epics.map((entry) => <option key={entry.id} value={entry.source_key}>{entry.source_key} · {entry.title}</option>)}
            </select>
          ) : null}
        </div>
        <div className="work-epics__counts" data-testid="work-epics-counts">
          <span><strong>{summary.shipped}</strong> of {summary.stories} {plural(summary.stories, "story", "stories")} shipped</span>
          <span><strong>{summary.tasksDone}</strong> of {summary.tasks} {plural(summary.tasks, "task")} done</span>
          {summary.tasksWithChanges ? (
            <span><strong className="work-epics__count--problem">{summary.tasksWithChanges}</strong> {plural(summary.tasksWithChanges, "task")} with changes</span>
          ) : null}
          {summary.decisions ? (
            <span><strong className="work-epics__count--attention">{summary.decisions}</strong> {plural(summary.decisions, "decision")} waiting for you</span>
          ) : null}
          <span><strong className="work-epics__mono">{costText(summary.cost)}</strong> API cost</span>
          {seatAmountText(summary.seat) ? (
            <span data-testid="work-epics-seat">
              <strong className="work-epics__mono">{seatAmountText(summary.seat)}</strong> seat: {SEAT_LABELS.equivalent}
            </span>
          ) : null}
          {summary.seat.unpricedCalls ? (
            <span data-testid="work-epics-unpriced">
              <strong>{summary.seat.unpricedCalls}</strong> seat {plural(summary.seat.unpricedCalls, "call")}: {SEAT_LABELS.unpriced}
            </span>
          ) : null}
        </div>
      </section>

      {stories.length === 0 ? (
        <p className="work-epics__note">This epic has no stories yet.</p>
      ) : (
        <section className="work-epics__stories" aria-label="Stories">
          <div className="work-epics__stories-head">
            <span>Story · one branch, one pull request each</span>
            <span>Tasks · status · result · API cost, seat at list price</span>
          </div>
          {stories.map((story) => <StoryRow key={story.item.id} story={story} open={story.item.id === openId}
            onOpenItem={onOpenItem} />)}
        </section>
      )}

      <p className="work-epics__note">
        Task status is set by the platform: proof test in the change and gates green = ✓, passed review = ✓✓, a review
        finding on the task = changes. Never from what the model says.
      </p>
    </div>
  );
}

function StoryRow({ story, open, onOpenItem }: { story: EpicStory; open: boolean; onOpenItem: (item: WorkItem) => void }) {
  const status = storyStatus(story);
  const shares = progressShares(story.tasks);
  const pr = storyPullRequest(story.runs);
  const decision = decisionRun(story.runs);
  const seat = storySeat(story.runs);
  const { item } = story;
  return (
    <details className="work-epics__story" open={open} data-testid="work-epics-story">
      <summary className="work-epics__summary">
        <span className="work-epics__story-main">
          <span className="work-epics__story-name">{item.source_key} · {item.title}</span>
          <span className="work-epics__story-progress">{storyProgress(story.tasks)}</span>
        </span>
        <span className="work-epics__bar" aria-hidden="true">
          <span className="work-epics__bar-done" style={{ width: `${shares.done}%` }} />
          <span className="work-epics__bar-changes" style={{ width: `${shares.changes}%` }} />
        </span>
        <StatusLabel label={status.label} tone={status.tone} />
        <span className="work-epics__pr">
          {pr && !pr.url ? <span>{pr.label}</span> : pr?.url ? <a href={pr.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>{pr.label}</a>
            : <span className="work-epics__muted">–</span>}
        </span>
        <span className="work-epics__cost">
          <span title="API cost">{costText(storyCost(story.runs))}</span>
          {hasSeat(seat) ? <span className="work-epics__seat" title={seatSentence(seat)}>{seatShort(seat)}</span> : null}
        </span>
      </summary>
      <div className="work-epics__body">
        {story.tasks.length ? <TaskList items={story.tasks} /> : <p className="work-epics__note">No task list yet.</p>}
        <div className="work-epics__actions">
          {decision?.session_id ? (
            <a className="work-area__button work-area__button--primary" href={chatSessionHref(decision.session_id)}>Open decision</a>
          ) : null}
          <button type="button" className="work-area__button" onClick={() => onOpenItem(item)}>Open the story</button>
        </div>
      </div>
    </details>
  );
}
