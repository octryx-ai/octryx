// The person's Macs on the phone: online or offline, paused or needing a login, how many jobs run there
// now and the Claude Code sessions open on each. The state words are the web's (devicesModel.deviceStatus).

import { useCallback, useEffect, useState } from "react";
import { StatusLabel, type StatusTone } from "../layout/StatusLabel";
import {
  CONNECT_COMMAND,
  deviceStatus,
  osLabel,
  readDevice,
  relativeTime,
  type DeviceStatus,
  type MyDevice,
} from "../chat/devices/devicesModel";
import { loadDevices } from "./mobileApi";
import { LiveRows } from "./ChatList";
import type { LiveSession } from "./mobileLiveSessions";
import { deviceRoutes } from "./engineSeatModel";
import { DetailHeader } from "./PageHeader";
import { useRefreshEvent } from "./pullToRefresh";

const POLL_MS = 10000;

const TONES: Record<DeviceStatus["tone"], StatusTone> = {
  running: "info",
  active: "success",
  neutral: "neutral",
  attention: "attention",
};

export function DevicesPage({
  liveSessions,
  onBack,
  onOpenLive,
}: {
  liveSessions: LiveSession[];
  onBack: () => void;
  onOpenLive: (session: LiveSession) => void;
}) {
  const [devices, setDevices] = useState<MyDevice[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const raw = (await loadDevices()) as { items?: unknown[] } | null;
      setDevices((raw?.items ?? []).map(readDevice).filter((item): item is MyDevice => item !== null));
      setError("");
    } catch {
      setError("Your Macs could not be loaded.");
    }
  }, []);
  useRefreshEvent(load);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => !document.hidden && void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);
  const online = devices?.filter((device) => device.connected).length ?? 0;
  return (
    <div className="m-screen">
      <DetailHeader
        title="Your Macs"
        subtitle={devices ? `${online} of ${devices.length} online` : undefined}
        onBack={onBack}
      />
      <main className="m-body">
        {error && (
          <p className="m-banner m-banner-problem" role="alert">
            {error}
          </p>
        )}
        {devices === null && !error && <p className="m-empty">Loading…</p>}
        {devices?.length === 0 && (
          <div className="m-empty">
            <p>No Mac is connected yet. On your Mac, run:</p>
            <code className="m-command">{CONNECT_COMMAND}</code>
          </div>
        )}
        {devices?.map((device) => {
          const status = deviceStatus(device);
          const sessions = liveSessions.filter((session) => session.deviceId === device.id);
          const facts: [string, string][] = (
            [
              ["Jobs", device.connected ? `${device.runningJobs} of ${device.maxParallelJobs} running` : ""],
              ["Last seen", device.connected ? "now" : relativeTime(device.lastSeenAt)],
              ["System", [osLabel(String(device.os)), device.clientVersion && `octryx-claude ${device.clientVersion}`].filter(Boolean).join(" · ")],
              ["Folders", device.folders.length ? `${device.folders.length} allowed` : ""],
              ["Billing", deviceRoutes(device)],
            ] as [string, string][]
          ).filter(([, value]) => value);
          return (
            <section key={device.id} className="m-panel m-device" aria-label={device.name}>
              <header className="m-device-head">
                <span className={`m-dot ${device.connected ? (device.runningJobs ? "m-dot-blue" : "m-dot-green") : "m-dot-idle"}`} aria-hidden="true" />
                <h2>{device.name}</h2>
                <StatusLabel label={status.label} tone={TONES[status.tone]} />
              </header>
              {device.needsLogin && !device.connected && (
                <p className="m-muted">
                  Its login ended. On the Mac, run <code>octryx-claude device enable</code>.
                </p>
              )}
              <dl className="m-facts">
                {facts.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
              {sessions.length > 0 && (
                <>
                  <h3 className="m-section">Coding sessions</h3>
                  <LiveRows sessions={sessions} onOpen={onOpenLive} />
                </>
              )}
            </section>
          );
        })}
      </main>
    </div>
  );
}
