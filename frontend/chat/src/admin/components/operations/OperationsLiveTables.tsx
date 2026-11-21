// The Devices and Seats tables shown under the Operations live runs.
import { DataTable } from "../../../layout/DataTable";
import { StatusLabel } from "../../../layout/StatusLabel";
import { agoText, deviceState, liveAge, seatText, slotsText } from "./operationsWords";
import { type OperationsLive, type OpsDevice, type OpsSeat } from "./operationsTypes";
import { Muted } from "./OperationsLiveCells";

export function DevicesTable({ devices, live, elapsed }: { devices: OpsDevice[]; live: OperationsLive; elapsed: number }) {
  return (
    <DataTable<OpsDevice>
      label="Devices"
      testId="ops-devices"
      rows={devices}
      rowKey={(device) => device.id}
      empty={{ text: "No device worked here in the last 24 hours." }}
      columns={[
        { key: "name", header: "Device", grow: true, render: (device) => (
          <span className="ops-two-lines">
            <span>{device.name}</span>
            <span className="ops-muted">{device.owner?.name ?? ""}</span>
          </span>
        ) },
        { key: "state", header: "State", nowrap: true, render: (device) => {
          const state = deviceState(device);
          const seen = device.online ? "" : agoText(liveAge(device.lastSeenAt, live.generatedAt, elapsed));
          return <StatusLabel label={state.label} tone={state.tone} title={seen ? `Last seen ${seen}` : undefined} />;
        } },
        { key: "version", header: "Version", nowrap: true, render: (device) => (
          <span className="ops-inline">
            <span>{device.clientVersion || "Unknown"}</span>
            {device.outdated ? <StatusLabel label="Outdated" tone="attention"
              title={device.servedVersion ? `Version ${device.servedVersion} is available.` : undefined} /> : null}
          </span>
        ) },
        { key: "jobs", header: "Jobs", nowrap: true, align: "end", render: (device) => slotsText(device) },
      ]}
    />
  );
}

export function SeatsTable({ seats }: { seats: OpsSeat[] }) {
  return (
    <DataTable<OpsSeat>
      label="Seats"
      testId="ops-seats"
      rows={seats}
      rowKey={(seat) => seat.user.id}
      empty={{ text: "No seat was used here in the last 24 hours." }}
      columns={[
        { key: "user", header: "Person", grow: true, render: (seat) => seat.user.name },
        { key: "five", header: "5 hours", nowrap: true, align: "end", render: (seat) => {
          const value = seatText(seat.fiveHourPct);
          return value.label ? (value.tone === "neutral" ? value.label : <StatusLabel label={value.label} tone={value.tone} />) : <Muted text="Not known" />;
        } },
        { key: "resets", header: "Resets at", nowrap: true, render: (seat) => clockText(seat.fiveHourResetsAt) || <Muted text="Not known" /> },
        { key: "seven", header: "7 days", nowrap: true, align: "end", render: (seat) => seatText(seat.sevenDayPct).label || <Muted text="Not known" /> },
      ]}
    />
  );
}

/** "16:20" in the viewer's time zone. */
function clockText(iso: string | null): string {
  if (!iso) return "";
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? "" : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
