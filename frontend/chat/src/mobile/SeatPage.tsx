// More › Seat: the person's own subscription on the phone, read-only. Signed in on which Mac, the
// Claude and Codex allowance windows when the server has them, and what the chosen Workspace allows (the two seat switches).
// Every change stays in the web app.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { readDevice, type MyDevice } from "../chat/devices/devicesModel";
import { loadDevices, loadSeatMode, loadUsage } from "./mobileApi";
import {
  readSeatStatus,
  resetText,
  seatRules,
  seatSignInText,
  type SeatRule,
  type SeatStatus,
} from "./engineSeatModel";
import { DetailHeader } from "./PageHeader";
import { useRefreshEvent } from "./pullToRefresh";

const value = <T,>(result: PromiseSettledResult<T>): T | null =>
  result.status === "fulfilled" ? result.value : null;

export function SeatPage({
  workspaceId,
  workspaceName,
  switcher,
  onBack,
}: {
  workspaceId: string;
  workspaceName: string;
  switcher?: ReactNode;
  onBack: () => void;
}) {
  const [status, setStatus] = useState<{ claude: SeatStatus; codex: SeatStatus } | null>(null);
  const [rules, setRules] = useState<SeatRule[] | null>(null);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    const [macs, usage, mode] = await Promise.allSettled([
      loadDevices(),
      workspaceId ? loadUsage(workspaceId) : Promise.reject(),
      workspaceId ? loadSeatMode(workspaceId) : Promise.reject(),
    ]);
    const raw = (value(macs) as { items?: unknown[] } | null)?.items;
    const devices = Array.isArray(raw)
      ? raw.map(readDevice).filter((item): item is MyDevice => item !== null)
      : null;
    setError(devices === null);
    setStatus({
      claude: readSeatStatus(devices, value(usage)),
      codex: readSeatStatus(devices, value(usage), "codex"),
    });
    setRules(workspaceId ? seatRules(value(mode)) : null);
  }, [workspaceId]);
  useRefreshEvent(load);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="m-screen">
      <DetailHeader
        title="Seat"
        subtitle="Your own subscription"
        onBack={onBack}
      />
      <main className="m-body">
        {error && (
          <p className="m-banner m-banner-problem" role="alert">
            Your Macs could not be loaded.
          </p>
        )}
        {!status && !error && <p className="m-empty">Loading…</p>}
        {status && (
          <SeatSection
            title="Claude subscription"
            label="Your Claude subscription"
            testId="m-seat-status"
            status={status.claude}
          />
        )}
        {status && (
          <SeatSection
            title="Codex"
            label="Your Codex sign-in"
            testId="m-seat-codex"
            status={status.codex}
            note={
              status.codex.windows.length
                ? null
                : "Codex uses your ChatGPT sign-in on the Mac. Its allowance shows here once a Codex seat run has reported it."
            }
          />
        )}
        {switcher}
        {rules && (
          <section
            className="m-seat-section"
            aria-label="What this Workspace allows"
            data-testid="m-seat-rules"
          >
            <h2 className="m-section">
              {workspaceName
                ? `Allowed in ${workspaceName}`
                : "Allowed in this Workspace"}
            </h2>
            <dl className="m-panel m-facts m-seat-rules">
              {rules.map((rule) => (
                <div key={rule.key}>
                  <dt>{rule.label}</dt>
                  <dd>
                    {rule.value}
                    {rule.note && (
                      <span className="m-seat-note">{rule.note}</span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="m-note">Change it in the web app.</p>
          </section>
        )}
      </main>
    </div>
  );
}

/** One seat (Claude or Codex): sign-in, then the 5 h / 7 d windows with reset times, or "Not reported yet". */
function SeatSection({
  title,
  label,
  testId,
  status,
  note = null,
}: {
  title: string;
  label: string;
  testId: string;
  status: SeatStatus;
  note?: string | null;
}) {
  return (
    <section className="m-seat-section" aria-label={label} data-testid={testId}>
      <h2 className="m-section">{title}</h2>
      <dl className="m-panel m-facts">
        <div>
          <dt>Sign-in</dt>
          <dd>{seatSignInText(status)}</dd>
        </div>
        {status.windows.map((window) => (
          <div key={window.key}>
            <dt>{window.label}</dt>
            <dd className={window.percent >= 80 ? "m-warn" : undefined}>
              {window.percent} % used
              {resetText(window.resetsAt) ? ` · resets ${resetText(window.resetsAt)}` : ""}
            </dd>
          </div>
        ))}
        {!status.windows.length && (
          <div>
            <dt>Allowance</dt>
            <dd>Not reported yet</dd>
          </div>
        )}
      </dl>
      {note && <p className="m-note">{note}</p>}
    </section>
  );
}
