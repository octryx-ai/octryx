import { useCallback, useEffect, useState } from "react";

import { useConfirmAction } from "../../admin/components/confirm/useConfirmAction";
import { ActionMenu } from "../../admin/components/workflowSurfaces/ActionMenu";
import { DataTable } from "../../layout/DataTable";
import { EmptyLine } from "../../layout/EmptyLine";
import { SidePanel } from "../../layout/SidePanel";
import { StatusLabel } from "../../layout/StatusLabel";
import { adminDeviceState, isRevocable, readAdminDevices, type AdminDevice } from "./adminDevicesModel";
import { adminRevokeDevice, loadAdminDevices } from "./devicesApi";
import { osLabel, relativeTime, serviceLabel } from "./devicesModel";
import { DeviceLoginValidity } from "./DeviceLoginValidity";
import "./devices.css";

// Admin › Platform › Devices (platform admins): every user's devices as a full-width table, without
// their folders; a row opens its facts in the side panel. An admin can revoke a device with a reason, never
// send it work or answer its approvals. Revoke sits in the row's ⋯ menu and the panel footer, confirmed in the app.

function DeviceFacts({ device }: { device: AdminDevice }) {
  const facts: Array<[string, string]> = [
    ["Owner", device.ownerName],
    ["System", osLabel(device.os)],
    ["Client", device.clientVersion ?? "—"],
    ["Service", serviceLabel(device.serviceKind)],
    ["Profiles", device.profiles.join(", ") || "—"],
    ["Folders", String(device.folderCount)],
    ["Jobs", `${device.runningJobs} of ${device.maxParallelJobs || 1}`],
    ["Registered", relativeTime(device.createdAt)],
    ["Last seen", device.connected ? "now" : relativeTime(device.lastSeenAt)],
    ...(device.revokedAt ? [["Revoked", relativeTime(device.revokedAt)] as [string, string]] : []),
    ["Device id", device.id],
  ];
  return (
    <dl className="platform-facts" data-testid="admin-device-facts">
      {facts.map(([label, value]) => (
        <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
      ))}
    </dl>
  );
}

export function AdminDevicesList() {
  const [devices, setDevices] = useState<AdminDevice[] | null>(null);
  const [problem, setProblem] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const { ask, dialog, notice } = useConfirmAction();

  const load = useCallback(async () => {
    try {
      setDevices(readAdminDevices(await loadAdminDevices()));
      setProblem("");
    } catch {
      setDevices([]);
      setProblem("The devices could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const askRevoke = (device: AdminDevice) => ask({
    title: `Revoke device ${device.name}?`,
    body: <p>{device.ownerName} can no longer send work to it; it has to be connected again.</p>,
    field: { label: "Reason for revoking", placeholder: "e.g. Laptop replaced", required: true },
    confirmLabel: `Revoke ${device.name}`,
    done: `Device ${device.name} revoked.`,
    run: async (reason) => {
      try {
        await adminRevokeDevice(device.id, reason);
      } catch {
        throw new Error("The device could not be revoked.");
      }
      await load();
    },
  });

  const open = devices?.find((device) => device.id === openId) ?? null;

  return (
    <section className="platform-page" aria-label="Devices" data-testid="admin-devices">
      <DeviceLoginValidity />
      {notice}
      {problem ? (
        <EmptyLine text={problem} action={{ label: "Try again", onClick: () => void load() }} testId="admin-devices-error" />
      ) : (
        <DataTable<AdminDevice>
          label="Devices"
          testId="admin-devices-table"
          loading={devices === null}
          rows={devices ?? []}
          rowKey={(device) => device.id}
          selectedKey={openId}
          onOpen={(device) => setOpenId(device.id)}
          empty={{ text: "No device is connected yet." }}
          columns={[
            { key: "device", header: "Device", grow: true, render: (device) => device.name },
            { key: "owner", header: "Owner", render: (device) => device.ownerName },
            { key: "system", header: "System", nowrap: true, render: (device) => osLabel(device.os) },
            { key: "client", header: "Client", nowrap: true, render: (device) => device.clientVersion ?? "—" },
            { key: "state", header: "State", nowrap: true, render: (device) => {
              const state = adminDeviceState(device);
              return <StatusLabel label={state.label} tone={state.tone} />;
            } },
            { key: "seen", header: "Last seen", nowrap: true,
              render: (device) => (device.connected ? "now" : relativeTime(device.lastSeenAt)) },
          ]}
          rowMenu={(device) => (isRevocable(device) ? (
            <ActionMenu row={{ objectName: device.name }}
              items={[{ label: "Revoke…", danger: true, onSelect: () => askRevoke(device) }]} />
          ) : null)}
        />
      )}
      {open ? (
        <SidePanel
          title={open.name}
          subtitle={`${open.ownerName} · ${osLabel(open.os)}`}
          onClose={() => setOpenId(null)}
          testId="admin-device-panel"
          footer={isRevocable(open) ? (
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger"
              onClick={() => askRevoke(open)}>Revoke…</button>
          ) : null}
        >
          <DeviceFacts device={open} />
        </SidePanel>
      ) : null}
      {dialog}
    </section>
  );
}
