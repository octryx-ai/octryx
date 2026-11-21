import { useState } from "react";

import { SettingsDrawer } from "../../admin/components/projectsTab/SettingsDrawer";
import { revokeDevice, updateDevice } from "./devicesApi";
import { deviceErrorText, osLabel, readDevice, relativeTime, serviceLabel } from "./devicesModel";
import type { MyDevice } from "./devicesModel";

// One device of the owner: its facts, its folder allowlist (the platform can only remove folders; adding
// happens on the device), rename and revoke.
export function DeviceDrawer({ device, onClose, onChanged, onRevoked }: {
  device: MyDevice;
  onClose: () => void;
  onChanged: (device: MyDevice) => void;
  onRevoked: (deviceId: string) => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(device.name);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [busy, setBusy] = useState(false);

  const patch = async (change: { name?: string; folders?: string[] }) => {
    setBusy(true);
    try {
      const next = readDevice(await updateDevice(device.id, change));
      if (next) onChanged(next);
      setProblem(null);
      setRenaming(false);
    } catch (error) {
      setProblem(deviceErrorText(error));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async () => {
    setBusy(true);
    try {
      await revokeDevice(device.id);
      onRevoked(device.id);
    } catch (error) {
      setProblem(deviceErrorText(error));
      setBusy(false);
    }
  };

  const footer = (
    <>
      {confirmRevoke ? (
        <>
          <span className="device-muted">The device token ends at once and running jobs stop.</span>
          <button type="button" className="admin-panel__action-btn" onClick={() => setConfirmRevoke(false)} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" onClick={() => void revoke()}
            disabled={busy}>
            Revoke now
          </button>
        </>
      ) : (
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger"
          onClick={() => setConfirmRevoke(true)}>
          Revoke device
        </button>
      )}
    </>
  );

  return (
    <SettingsDrawer eyebrow="My device" title={device.name} size="detail" onClose={onClose} footer={footer}>
      {problem ? <p className="work-area__error" role="alert">{problem}</p> : null}
      <section className="work-detail__section">
        <h3>Device</h3>
        <dl className="work-detail__kv">
          <dt>Name</dt>
          <dd>
            {renaming ? (
              <form className="device-rename" onSubmit={(event) => { event.preventDefault(); void patch({ name }); }}>
                <input className="admin-panel__input" aria-label="Device name" value={name} maxLength={80}
                  onChange={(event) => setName(event.target.value)} autoFocus />
                <button type="submit" className="admin-panel__action-btn" disabled={busy || !name.trim()}>Save</button>
                <button type="button" className="admin-panel__action-btn" onClick={() => { setRenaming(false); setName(device.name); }}>
                  Cancel
                </button>
              </form>
            ) : (
              <span className="device-row">
                {device.name}
                <button type="button" className="admin-panel__action-btn" onClick={() => setRenaming(true)}>Rename</button>
              </span>
            )}
          </dd>
          <dt>Id</dt>
          <dd className="device-mono">{device.id}</dd>
          <dt>System</dt>
          <dd>{osLabel(device.os)} · {serviceLabel(device.serviceKind)}</dd>
          <dt>Version</dt>
          <dd>{device.clientVersion ? `octryx-claude ${device.clientVersion}` : "unknown"}</dd>
          <dt>Connection</dt>
          <dd>{device.connected ? "connected · outbound WebSocket" : `offline · last seen ${relativeTime(device.lastSeenAt)}`}</dd>
          <dt>Parallel jobs</dt>
          <dd>{device.runningJobs} running · limit {device.maxParallelJobs}</dd>
          <dt>Credential</dt>
          <dd>device token, short-lived and refreshed by the device; revoking ends it at once</dd>
        </dl>
      </section>
      <section className="work-detail__section">
        <h3>Allowed folders</h3>
        <p className="device-muted">
          Jobs can only start in these folders (and their subfolders). Removing here narrows the list at once; adding is
          only possible on the device (<span className="device-mono">octryx-claude device folders add</span>), so a stolen
          platform login cannot widen it.
        </p>
        <div>
          {device.folders.length === 0 ? <p className="device-muted">No folder is allowed.</p> : null}
          {device.folders.map((folder) => (
            <div key={folder} className="device-folder">
              <span>{folder}</span>
              <button type="button" className="admin-users__row-btn" title="Remove" aria-label={`Remove ${folder}`}
                disabled={busy} onClick={() => void patch({ folders: device.folders.filter((item) => item !== folder) })}>
                ✕
              </button>
            </div>
          ))}
        </div>
      </section>
    </SettingsDrawer>
  );
}
