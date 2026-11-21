import { useCallback, useEffect, useState } from "react";

import { loadMyDevices, pauseAllDevices } from "./devicesApi";
import { CONNECT_COMMAND, deviceErrorText, deviceStatus, osLabel, readMyDevices, relativeTime, serviceLabel } from "./devicesModel";
import type { MyDevice, MyDevices } from "./devicesModel";
import { PageHeader } from "../../layout/PageHeader";
import { DeviceDrawer } from "./DeviceDrawer";
import { MyPhonesSection } from "./MyPhonesSection";

// My settings → Devices: the caller's own octryx-claude devices, the connect command, "Pause all my
// devices" (personal kill switch) and a drawer per device (folders, rename, revoke).
export function MyDevicesPage({ pollMs = 15000 }: { pollMs?: number }) {
  const { devices, problem, openId, setOpenId, copied, togglePauseAll, copy, replace } = useMyDevices(pollMs);
  const open = devices?.items.find((item) => item.id === openId) ?? null;
  const allPaused = devices?.allPaused ?? false;

  return (
    <>
      <div className="admin-panel__header">
        <PageHeader eyebrow="My settings" title="Devices" purpose="The computers and phones that run work for you."
          secondary={<PauseAllSwitch allPaused={allPaused} disabled={!devices?.items.length} onToggle={() => void togglePauseAll()} />} />
      </div>
      <div className="admin-panel__body">
        <div className="admin-panel__stack">
          {problem ? <p className="work-area__error" role="alert">{problem}</p> : null}
          {allPaused ? (
            <div className="device-warn" role="status">
              All your devices are paused: running jobs were stopped and new requests can only run on the Server.
            </div>
          ) : null}
          <ConnectDeviceCard copied={copied} onCopy={() => void copy()} />
          {devices === null && !problem ? <p className="device-muted" role="status">Loading your devices…</p> : null}
          {devices && devices.items.length === 0 ? (
            <p className="admin-panel__hint">No device is connected yet.</p>
          ) : null}
          {devices && devices.items.length > 0 ? (
            <DeviceTable devices={devices} onOpen={setOpenId} />
          ) : null}
          <MyPhonesSection />
          <p className="admin-panel__hint">
            Devices belong to you only. Admins see that a device exists, its status and its audit trail, and can revoke
            it — they can never send it work or answer its approvals.
          </p>
        </div>
      </div>
      {open ? (
        <DeviceDrawer
          device={open}
          onClose={() => setOpenId(null)}
          onChanged={(next) => replace(next)}
          onRevoked={(id) => {
            setOpenId(null);
            replace(null, id);
          }}
        />
      ) : null}
    </>
  );
}

// The caller's devices, polled while the page is visible, with pause all, copy command and a changed or removed device.
function useMyDevices(pollMs: number) {
  const [devices, setDevices] = useState<MyDevices | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const listed = readMyDevices(await loadMyDevices());
      setDevices(listed);
      setProblem(listed ? null : "The server's answer was not a list of devices.");
    } catch {
      setProblem("Your devices could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => {
      if (document.visibilityState !== "hidden") void load();
    }, pollMs);
    return () => clearInterval(timer);
  }, [load, pollMs]);

  const togglePauseAll = async () => {
    if (!devices) return;
    try {
      setDevices(readMyDevices(await pauseAllDevices(!devices.allPaused)) ?? devices);
      setProblem(null);
    } catch (error) {
      setProblem(deviceErrorText(error));
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(CONNECT_COMMAND);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const replace = (next: MyDevice | null, removedId?: string) => {
    setDevices((current) => {
      if (!current) return current;
      const items = current.items
        .filter((item) => item.id !== removedId)
        .map((item) => (next && item.id === next.id ? next : item));
      return { items, allPaused: items.length > 0 && items.every((item) => item.paused) };
    });
  };
  return { devices, problem, openId, setOpenId, copied, togglePauseAll, copy, replace };
}

function PauseAllSwitch({ allPaused, disabled, onToggle }: { allPaused: boolean; disabled: boolean; onToggle: () => void }) {
  return (
    <div className="device-row">
      <span className="device-muted">Pause all my devices</span>
      <span
        className={`toggle-switch ${allPaused ? "toggle-switch--on" : ""}`}
        role="switch"
        aria-checked={allPaused}
        aria-label="Pause all my devices"
        aria-disabled={disabled}
        title="Personal kill switch: devices reject new jobs and stop running ones"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(event) => {
          if (event.key === " " || event.key === "Enter") {
            event.preventDefault();
            onToggle();
          }
        }}
      />
    </div>
  );
}

function ConnectDeviceCard({ copied, onCopy }: { copied: boolean; onCopy: () => void }) {
  return (
    <section className="admin-panel__card">
      <div className="admin-panel__section-header"><span>Connect a device</span></div>
      <p className="admin-panel__hint">
        On the device, after installing octryx-claude (Agents → Install), run this once. It registers the device
        to you, installs the background service and connects outbound — no inbound port is opened.
      </p>
      <div className="device-cmd">
        <code>{CONNECT_COMMAND}</code>
        <button type="button" className="admin-panel__action-btn" onClick={onCopy}>
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </section>
  );
}

function DeviceTable({ devices, onOpen }: { devices: MyDevices; onOpen: (id: string) => void }) {
  return (
    <table className="admin-panel__table device-cards">
      <thead>
        <tr><th>Device</th><th>Status</th><th>Service</th><th>Profiles</th><th>Folders</th><th>Last seen</th><th /></tr>
      </thead>
      <tbody>
        {devices.items.map((device) => {
          const status = deviceStatus(device);
          return (
            <tr key={device.id} className={status.offline ? "admin-panel__row--inactive" : undefined}>
              <td data-label="Device">
                <div className="device-name">{device.name}</div>
                <div className="device-muted">{osLabel(device.os)} · {device.id}</div>
              </td>
              <td data-label="Status"><span className={`work-badge work-badge--${status.tone}`}>{status.label}</span></td>
              <td data-label="Service" className="admin-panel__cell--muted">
                {serviceLabel(device.serviceKind)}{device.clientVersion ? ` · ${device.clientVersion}` : ""}
              </td>
              <td data-label="Profiles">{device.profiles.join(", ") || "—"}</td>
              <td data-label="Folders">{device.folders.length}</td>
              <td data-label="Last seen" className="admin-panel__cell--muted">
                {device.connected ? "now" : relativeTime(device.lastSeenAt)}
              </td>
              <td data-label="">
                <button type="button" className="admin-panel__action-btn" onClick={() => onOpen(device.id)}>
                  Details
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
