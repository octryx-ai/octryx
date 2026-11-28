import type { JobDetail, JobEvent, JobPhase } from "./companionJobModel";

export type EventView = { text: string; at: string | null; count: number; technical: boolean };

export function eventViews(events: JobEvent[], { technical = false } = {}): EventView[] {
  const views: EventView[] = [];
  for (const event of events) {
    if (event.technical && !technical) continue;
    const last = views[views.length - 1];
    if (last && last.text === event.text && last.technical === event.technical) {
      last.count += 1;
      continue;
    }
    views.push({ text: event.text, at: event.at, count: 1, technical: event.technical });
  }
  return views;
}

export const technicalCount = (events: JobEvent[]) => events.filter((event) => event.technical).length;

export function currentSentence(job: JobDetail): string {
  const newest = eventViews(job.currentStep ? [job.currentStep, ...job.events] : job.events)[0];
  return newest?.text ?? "";
}

/** When every phase is pending although the run moved on (it lost its current node), the phase index decides. */
export function phaseStates(job: JobDetail): JobPhase[] {
  const phases = job.phases;
  if (!phases.length || phases.some((phase) => phase.state !== "pending")) return phases;
  if (job.state === "done") return phases.map((phase) => ({ ...phase, state: "done" }));
  const reached = job.phaseIndex ? job.phaseIndex - 1 : -1;
  if (reached < 0) return phases;
  const current = job.state === "problem" ? "problem" : "active";
  return phases.map((phase, index) => ({ ...phase, state: index < reached ? "done" : index === reached ? current : "pending" }));
}
