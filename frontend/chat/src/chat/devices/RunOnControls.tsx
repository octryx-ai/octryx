import { useCallback, useEffect, useRef, useState } from "react";

import { DeviceModelPill } from "./DeviceModelPill";
import { loadDeviceRunsPolicy, loadMyDevices } from "./devicesApi";
import { deviceRunsBlocked, readDeviceRunsPolicy, workspaceAllowsSeat, type DeviceRunsPolicy } from "./deviceRunsPolicyModel";
import { deviceStatus, osLabel, readMyDevices, relativeTime, type MyDevice } from "./devicesModel";
import { SERVER_TARGET, setExecutionTarget, useExecutionTarget, type DeviceProfile } from "./executionTarget";
import "./devices.css";

// The composer's "Run on" control: Server or one of the caller's own devices, and for a
// device its folder (from the device's allowlist) and profile (governed, or seat when the device has a seat
// login), and the model (`DeviceModelPill`). Offline or paused devices are listed but cannot be picked.
function ServerIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="device-pill-icon">
      <rect x="4" y="4" width="16" height="6" rx="1.5" /><rect x="4" y="14" width="16" height="6" rx="1.5" />
      <path d="M8 7h.01M8 17h.01" />
    </svg>
  );
}

function LaptopIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="device-pill-icon">
      <rect x="4" y="5" width="16" height="10" rx="1.5" /><path d="M2 19h20" />
    </svg>
  );
}

function deviceLine(device: MyDevice): string {
  const status = deviceStatus(device);
  const profiles = device.profiles.includes("seat") && device.seatLogin ? "seat or governed" : "governed only";
  if (device.needsLogin && status.offline) {
    return `${osLabel(device.os)} · needs login — re-enable it there (octryx-claude device disable, then device enable)`;
  }
  if (status.offline) return `${osLabel(device.os)} · offline since ${relativeTime(device.lastSeenAt)} — not selectable`;
  if (device.paused) return `${osLabel(device.os)} · paused — not selectable`;
  const load = device.runningJobs > 0 ? `${device.runningJobs} running (limit ${device.maxParallelJobs})` : "idle";
  return `${osLabel(device.os)} · online · ${load} · ${profiles}`;
}

const seatAvailable = (device: MyDevice | undefined) => !!device && device.profiles.includes("seat") && device.seatLogin;

// The caller's devices (read again when the list opens), the Workspace's device-run policy and the open list that
// closes on an outside click or Escape.
function useRunOnControl(projectId: string) {
  const [devices, setDevices] = useState<MyDevice[]>([]);
  const [policy, setPolicy] = useState<DeviceRunsPolicy | null>(null);
  const [open, setOpen] = useState(false);
  const shellRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      setDevices(readMyDevices(await loadMyDevices())?.items ?? []);
    } catch {
      setDevices([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!projectId) {
      setPolicy(null);
      return;
    }
    let current = true;
    loadDeviceRunsPolicy(projectId)
      .then((raw) => { if (current) setPolicy(readDeviceRunsPolicy(raw)); })
      .catch(() => { if (current) setPolicy(null); });
    return () => { current = false; };
  }, [projectId, open]);

  useEffect(() => {
    if (!open) return undefined;
    void load();
    const close = (event: MouseEvent) => {
      if (shellRef.current && !shellRef.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open, load]);

  return { devices, policy, open, setOpen, shellRef };
}

type ExecutionTarget = ReturnType<typeof useExecutionTarget>;
type DeviceTarget = Extract<ExecutionTarget, { kind: "device" }>;

function RunOnPopover({ sessionId, target, devices, blocked, setOpen, pickDevice }: {
  sessionId: string | null | undefined;
  target: ExecutionTarget;
  devices: MyDevice[];
  blocked: string | null;
  setOpen: (open: boolean) => void;
  pickDevice: (device: MyDevice) => void;
}) {
  return (
    <div className="device-popover" role="listbox" aria-label="Where this request runs">
      <div className="device-pop-label">Platform</div>
      <button type="button" role="option" aria-selected={target.kind === "server"}
        className={`device-opt ${target.kind === "server" ? "is-selected" : ""}`}
        onClick={() => { setExecutionTarget(sessionId, SERVER_TARGET); setOpen(false); }}>
        <ServerIcon />
        <span><b>Server</b><small>Platform agent, Workspace connectors and knowledge — as today</small></span>
        <span />
      </button>
      <div className="device-pop-label">My devices</div>
      {blocked ? <div className="device-pop-note">{blocked}</div> : null}
      {devices.length === 0 ? <div className="device-pop-note">No device is connected yet.</div> : null}
      {devices.map((device) => {
        const status = deviceStatus(device);
        const unavailable = status.offline || device.paused || blocked !== null;
        return (
          <button key={device.id} type="button" role="option" disabled={unavailable}
            aria-selected={target.kind === "device" && target.deviceId === device.id}
            className={`device-opt ${target.kind === "device" && target.deviceId === device.id ? "is-selected" : ""}`}
            onClick={() => pickDevice(device)}>
            <LaptopIcon />
            <span><b>{device.name}</b><small>{deviceLine(device)}</small></span>
            <span className={`device-dot ${unavailable ? "device-dot--off" : device.runningJobs > 0 ? "device-dot--busy" : "device-dot--on"}`} />
          </button>
        );
      })}
      <div className="device-pop-foot">
        <span>Only your own devices are listed.</span>
        <button type="button" onClick={() => { window.location.href = "/chat?area=personal"; }}>Manage devices →</button>
      </div>
    </div>
  );
}

function DeviceTargetFields({ sessionId, projectId, target, selected, policy, composerDisabled }: {
  sessionId: string | null | undefined;
  projectId: string;
  target: DeviceTarget;
  selected: MyDevice | undefined;
  policy: DeviceRunsPolicy | null;
  composerDisabled: boolean;
}) {
  return (
    <>
      <label className="composer-pill" title="Working folder on the device (from the device allowlist)">
        <span className="composer-pill__display">
          <svg viewBox="0 0 24 24" aria-hidden="true" className="device-pill-icon"><path d="M3 7h6l2 2h10v10H3z" /></svg>
          <span>{target.folder || "No folder allowed"}</span>
        </span>
        <select aria-label="Working folder" value={target.folder} disabled={composerDisabled || !selected}
          onChange={(event) => setExecutionTarget(sessionId, { ...target, folder: event.target.value })}>
          {(selected?.folders ?? (target.folder ? [target.folder] : [])).map((folder) => (
            <option key={folder} value={folder}>{folder}</option>
          ))}
        </select>
      </label>
      <label className="composer-pill" title="octryx-claude profile on the device">
        <span className="composer-pill__display">
          <svg viewBox="0 0 24 24" aria-hidden="true" className="device-pill-icon">
            <path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" />
          </svg>
          <span>Profile: {target.profile}</span>
        </span>
        <select aria-label="Profile" value={target.profile} disabled={composerDisabled}
          onChange={(event) => setExecutionTarget(sessionId, { ...target, profile: event.target.value as DeviceProfile })}>
          <option value="governed">Profile: governed</option>
          {(seatAvailable(selected) && workspaceAllowsSeat(policy)) || target.profile === "seat" ? (
            <option value="seat">Profile: seat (your subscription)</option>
          ) : null}
        </select>
      </label>
      <DeviceModelPill sessionId={sessionId} projectId={projectId} target={target} disabled={composerDisabled} />
    </>
  );
}

export function RunOnControls({ sessionId, projectId, workspaceName, composerDisabled }: {
  sessionId: string | null | undefined;
  projectId: string;
  workspaceName: string;
  composerDisabled: boolean;
}) {
  const target = useExecutionTarget(sessionId);
  const { devices, policy, open, setOpen, shellRef } = useRunOnControl(projectId);

  const selected = target.kind === "device" ? devices.find((device) => device.id === target.deviceId) : undefined;
  const blocked = deviceRunsBlocked(policy, workspaceName);
  const label = target.kind === "device" ? `Run on: ${selected?.name ?? "your device"}` : "Run on: Server";

  const pickDevice = (device: MyDevice) => {
    const folder = target.kind === "device" && device.folders.includes(target.folder) ? target.folder : device.folders[0] ?? "";
    setExecutionTarget(sessionId, { kind: "device", deviceId: device.id, folder, profile: "governed", model: "" });
    setOpen(false);
  };

  return (
    <div className="device-target" ref={shellRef}>
      {open ? (
        <RunOnPopover sessionId={sessionId} target={target} devices={devices} blocked={blocked} setOpen={setOpen}
          pickDevice={pickDevice} />
      ) : null}
      <button type="button" className={`composer-pill ${target.kind === "device" ? "composer-pill--active" : ""}`}
        title="Where this request runs" aria-haspopup="listbox" aria-expanded={open} disabled={composerDisabled}
        onClick={() => setOpen((current) => !current)}>
        <span className="composer-pill__display">
          {target.kind === "device" ? <LaptopIcon /> : <ServerIcon />}
          <span>{label}</span>
        </span>
      </button>
      {target.kind === "device" ? (
        <DeviceTargetFields sessionId={sessionId} projectId={projectId} target={target} selected={selected}
          policy={policy} composerDisabled={composerDisabled} />
      ) : null}
    </div>
  );
}
