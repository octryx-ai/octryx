import { useCallback, useEffect, useRef, useState } from "react";
import { groupAttention, isDone, needsYou, problemItems } from "./companionGroups";
import { type Attention, type AttentionItem } from "./companionTypes";
import { HANDOVER_ACCEPTED, quietUntilText } from "./companionHandoverModel";
import { RUN_STATE_LABEL, humanize, runStatePhrase, targetPhrase } from "./companionLabels";
import { CompanionFooter, type CompanionFooterProps } from "./CompanionFooter";
import { ItemCard, type Accepted } from "./CompanionItemCard";
import { CompanionJobs } from "./CompanionJobs";
import { SidePanel } from "../../layout/SidePanel";
import type { WatchJob } from "./CompanionJobDetail";

// The companion's side panel: the design system's SidePanel over the dimmed page, like every other side panel.
// Escape, ✕ and a click on the dimmed page close it. What needs the
// person comes first, then problems, what runs and what is done, each run in exactly one of them;
// quiet hours and browser notifications sit behind the gear. An answered card stays where it is with "Answered" for a
// moment and is removed afterwards, so the next click hits its target. "Jobs" lists the person's or the team's
// runs.

type PanelProps = {
  attention: Attention | null;
  problem: string | null;
  onClose: () => void;
  onDone: (key: string) => void;
  onOpenAgents: () => void;
  footer: CompanionFooterProps;
  watchJob: WatchJob;
  /** Opens a chat thread (an accepted handover's new thread of the receiver). */
  onOpenSession?: (sessionId: string) => void;
  isAdmin?: boolean;
  now?: () => number;
  /** How long an answered card says "Answered" before it leaves. */
  answeredMs?: number;
};

type View = "now" | "jobs" | "settings";
const VIEWS: { key: Exclude<View, "settings">; label: string }[] = [{ key: "now", label: "Now" }, { key: "jobs", label: "Jobs" }];
export const ANSWERED_MS = 1_500;

/** Re-renders every second while a countdown runs, else every 30 s, so relative times never go stale. */
function useNow(fast: boolean, now: () => number): number {
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((value) => value + 1), fast ? 1_000 : 30_000);
    return () => clearInterval(timer);
  }, [fast]);
  return now();
}

/** Answered cards held at their place until they leave, even when a reload already dropped them. */
function useHeld(items: AttentionItem[], onDone: (key: string) => void, answeredMs: number) {
  const [held, setHeld] = useState<Record<string, AttentionItem>>({});
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  // The key that came before each held card, so it is put back where it stood.
  const before = useRef<Record<string, string | null>>({});
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const answer = useCallback((key: string) => {
    const index = items.findIndex((entry) => entry.key === key);
    if (index < 0) { onDone(key); return; }
    before.current[key] = index > 0 ? items[index - 1].key : null;
    setHeld((current) => ({ ...current, [key]: items[index] }));
    timers.current.push(setTimeout(() => {
      setHeld((current) => {
        const { [key]: _gone, ...rest } = current;
        return rest;
      });
      delete before.current[key];
      onDone(key);
    }, answeredMs));
  }, [answeredMs, items, onDone]);
  const withHeld = (list: AttentionItem[], belongs: (item: AttentionItem) => boolean) => {
    const result = [...list];
    for (const item of Object.values(held)) {
      if (!belongs(item) || result.some((entry) => entry.key === item.key)) continue;
      const after = before.current[item.key];
      const at = after ? result.findIndex((entry) => entry.key === after) + 1 : 0;
      result.splice(Math.max(0, at), 0, item);
    }
    return result;
  };
  return { held, answer, withHeld };
}

function Section({ title, items, empty, testId, held, ...rest }: {
  title: string; items: AttentionItem[]; empty?: string; testId: string; now: number; held: Record<string, AttentionItem>;
  onAnswered: (key: string) => void; onAccepted: Accepted;
}) {
  if (!items.length && !empty) return null;
  const open = items.filter((item) => !held[item.key]).length;
  return (
    <section className="octryx-panel__section" aria-label={title} data-testid={testId}>
      <h3 className="octryx-panel__heading">{title}{open ? ` (${open})` : ""}</h3>
      {items.length ? (
        <ul className="octryx-panel__list">
          {items.map((item) => <ItemCard key={item.key} item={item} answered={Boolean(held[item.key])} {...rest} />)}
        </ul>
      ) : <p className="octryx-panel__hint">{empty}</p>}
    </section>
  );
}

const GEAR = (
  <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8">
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" />
  </svg>
);

export function CompanionPanel({
  attention, problem, onClose, onDone, onOpenAgents, footer, watchJob, onOpenSession, isAdmin = false, now = Date.now,
  answeredMs = ANSWERED_MS,
}: PanelProps) {
  const [view, setView] = useState<View>("now");
  const [accepted, setAccepted] = useState<string | null>(null);
  const items = attention?.items ?? [];
  const time = useNow(items.some((item) => item.expiresAt), now);
  const { held, answer, withHeld } = useHeld(items, onDone, answeredMs);
  const onAccepted: Accepted = (sessionId) => {
    setAccepted(HANDOVER_ACCEPTED);
    if (sessionId) onOpenSession?.(sessionId);
  };
  const shared = { now: time, held, onAnswered: answer, onAccepted };
  const quiet = attention ? quietUntilText(attention.quiet) : "";
  // Each run once, by precedence Needs you > Problems > Running > Done; Running lists only runs still going.
  const groups = groupAttention(items, attention?.running ?? []);
  const running = groups.running;
  const isNeeds = (item: AttentionItem) => needsYou([item]).length > 0;
  const isProblem = (item: AttentionItem) => problemItems([item]).length > 0;
  const headerActions = (
    <>
      {quiet ? <span className="octryx-panel__meta" data-testid="octryx-quiet">{quiet}</span> : null}
      <button type="button" className="admin-panel__action-btn octryx-panel__gear" aria-label="Notification settings"
        title="Notification settings" aria-pressed={view === "settings"} data-testid="octryx-settings"
        onClick={() => setView((current) => (current === "settings" ? "now" : "settings"))}>
        {GEAR}
      </button>
    </>
  );
  return (
    <SidePanel title="Octryx" onClose={onClose} size="narrow" testId="octryx-panel" headerActions={headerActions}
      tabs={view === "settings" ? undefined
        : { tabs: VIEWS, value: view, onChange: (key) => setView(key as View), label: "Show", idPrefix: "octryx-view", testId: "octryx-views" }}>
      <div className="octryx-panel__body">
        {view === "settings" ? (
          <>
            <button type="button" className="admin-panel__action-btn octryx-jobs__back" onClick={() => setView("now")}>← Back</button>
            <CompanionFooter {...footer} />
          </>
        ) : null}
        {view === "jobs" ? <CompanionJobs watchJob={watchJob} isAdmin={isAdmin} now={now} /> : null}
        {view === "now" ? (
          <>
            {problem ? <p className="octryx-panel__hint" role="status" data-testid="octryx-problem">{problem}</p> : null}
            {accepted ? <p className="octryx-panel__hint" role="status" data-testid="octryx-accepted">{accepted}</p> : null}
            <Section title="Needs you" items={withHeld(groups.needs, isNeeds)} empty="Nothing needs you right now." testId="octryx-needs" {...shared} />
            <Section title="Problems" items={withHeld(groups.problems, isProblem)} testId="octryx-problems" {...shared} />
            {running.length ? (
              <section className="octryx-panel__section" aria-label="Running" data-testid="octryx-working">
                <h3 className="octryx-panel__heading">Running ({running.length})</h3>
                <ul className="octryx-panel__list">
                  {running.map((run) => (
                    <li key={run.key} className={`octryx-panel__run octryx-panel__run--${run.state}`}>
                      <strong>{run.label}</strong>
                      <span className="octryx-panel__meta">
                        {[runStatePhrase(run.status, run.currentNode, run.waitingKind, RUN_STATE_LABEL[run.state], run.pauseReason),
                          runStatePhrase(run.status, run.currentNode, run.waitingKind, "") === "Waiting for merge" ? "" : humanize(run.currentNode), run.target?.deviceName ? `on ${run.target.deviceName}${run.target.online === false ? " · offline" : ""}` : targetPhrase(run.target)].filter(Boolean).join(" · ")}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {/* The window is in the heading: Done keeps runs of three days, Jobs lists the last 24 hours, so "Done (4)" next to
                one finished job is explained where it is read. */}
            <Section title="Done in the last 3 days" items={withHeld(groups.done, isDone)} testId="octryx-done" {...shared} />
            <button type="button" className="admin-panel__action-btn" onClick={onOpenAgents}>Open Agents</button>
          </>
        ) : null}
      </div>
    </SidePanel>
  );
}
