// Operations on the phone: the desktop's Operations › Live as cards,
// the most urgent first. Each card says its state, one line of where or what, and its main action (answer or open
// the run; Abort sits in the run's own "Steer the run"). Devices and seats follow. Not the "Live" page of a Mac's
// Claude Code session (LivePage.tsx): this one is about the platform's runs.

import { StatusLabel } from "../layout/StatusLabel";
import { agoText, countTiles, deviceState, liveAge, runMeta, runStateLabel, seatText, slotsText } from "../admin/components/operations/operationsWords";
import { cardLine, runMainAction } from "../admin/components/operations/operationsActions";
import { type OpsRun } from "../admin/components/operations/operationsTypes";
import { updatedText, useOperationsLive } from "../admin/components/operations/useOperationsLive";
import { startSession } from "./mobileSession";
import { DetailHeader } from "./PageHeader";
import { useRefreshEvent } from "./pullToRefresh";

const OPTIONS = { renew: startSession };

export function OperationsPage({
  workspace,
  onBack,
  onOpenRun,
}: {
  workspace: string;
  onBack: () => void;
  onOpenRun: (runId: string, title: string) => void;
}) {
  const { live, error, loadedAt, now, reload } = useOperationsLive(workspace, OPTIONS);
  useRefreshEvent(reload);
  const elapsed = loadedAt === null ? 0 : (now - loadedAt) / 1000;
  const counts = live ? countTiles(live.counts) : [];
  return (
    <div className="m-screen">
      <DetailHeader title="Operations" subtitle={updatedText(loadedAt, now) || undefined} onBack={onBack} />
      <main className="m-body" data-testid="m-operations">
        {error && (
          <p className="m-banner m-banner-problem" role="alert">
            {error}
          </p>
        )}
        {live === null && !error && <p className="m-empty">Loading…</p>}
        {live && (
          <ul className="m-ops-counts" aria-label="Runs by state">
            {counts.map((tile) => (
              <li key={tile.key} className={`m-ops-count m-ops-count-${tile.tone}`}>
                <span className="m-ops-count-value">{tile.value}</span>
                <span className="m-ops-count-label">{tile.label}</span>
              </li>
            ))}
          </ul>
        )}
        {live && live.runs.length === 0 && (
          <div className="m-empty">
            <p>No run is active right now.</p>
          </div>
        )}
        {live && live.runs.length > 0 && (
          <ul className="m-cards" aria-label="Active runs">
            {live.runs.map((run) => (
              <li key={run.id}>
                <RunCard run={run} line={cardLine(run, live.devices)} elapsed={elapsed} onOpen={() => onOpenRun(run.id, run.title)} />
              </li>
            ))}
          </ul>
        )}
        {live && live.devices.length > 0 && (
          <>
            <h2 className="m-section">Devices</h2>
            <ul className="m-rows m-group">
              {live.devices.map((device) => {
                const state = deviceState(device);
                const seen = device.online ? "" : agoText(liveAge(device.lastSeenAt, live.generatedAt, elapsed));
                return (
                  <li key={device.id}>
                    <div className="m-row m-row-plain m-ops-row">
                      <span className="m-row-text">
                        <b>{device.name}</b>
                        <span>
                          {[device.owner?.name, device.clientVersion && `Version ${device.clientVersion}`,
                            device.online ? `${slotsText(device)} jobs` : seen && `seen ${seen}`].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      <span className="m-ops-labels">
                        {device.outdated && <StatusLabel label="Outdated" tone="attention" />}
                        <StatusLabel label={state.label} tone={state.tone} />
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}
        {live && live.seats.length > 0 && (
          <>
            <h2 className="m-section">Seats</h2>
            <ul className="m-rows m-group">
              {live.seats.map((seat) => {
                const five = seatText(seat.fiveHourPct);
                return (
                  <li key={seat.user.id}>
                    <div className="m-row m-row-plain m-ops-row">
                      <span className="m-row-text">
                        <b>{seat.user.name}</b>
                        <span>{seat.fiveHourResetsAt ? `5-hour window resets at ${clockText(seat.fiveHourResetsAt)}` : "5-hour window"}</span>
                      </span>
                      {five.label && <StatusLabel label={five.label} tone={five.tone} />}
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </main>
    </div>
  );
}

function RunCard({ run, line, elapsed, onOpen }: { run: OpsRun; line: string; elapsed: number; onOpen: () => void }) {
  const state = runStateLabel({ ...run, idleSeconds: run.idleSeconds === null ? null : run.idleSeconds + Math.round(elapsed) });
  const answer = runMainAction(run)?.label === "Answer";
  return (
    <section className={`m-panel m-ops-card m-ops-card-${state.tone}`} aria-label={run.title}>
      <header className="m-ops-card-head">
        <span className="m-row-text">
          <b>{run.title}</b>
          <span>{runMeta(run)}</span>
        </span>
        <StatusLabel label={state.label} tone={state.tone} title={state.title} />
      </header>
      {line && <p className="m-ops-line">{line}</p>}
      {state.title && run.state !== "working" && <p className="m-ops-why">{state.title}</p>}
      <button type="button" className={`${answer ? "m-primary" : "m-secondary"} m-full`} onClick={onOpen}>
        {answer ? "Answer" : "Open run"}
      </button>
    </section>
  );
}

function clockText(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? "" : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
