// Remote device sessions: the device list as the owner sees it, and the labels the UI shows.

import { formatRelative, timeOf } from "../../admin/utils/dateTime";

export type DeviceOs = "macos" | "linux" | "wsl2";

export type MyDevice = {
  id: string;
  name: string;
  os: DeviceOs | string;
  paused: boolean;
  connected: boolean;
  runningJobs: number;
  maxParallelJobs: number;
  profiles: string[];
  seatLogin: boolean;
  /** The Codex seat's ChatGPT login on this Mac, yes/no while it is online. */
  codexSeatLogin: boolean;
  // Offline with a dead credential it could not renew with its device key: re-enable it on the device.
  needsLogin: boolean;
  clientVersion: string | null;
  serviceKind: string | null;
  folders: string[];
  createdAt: string | null;
  lastSeenAt: string | null;
};

export type MyDevices = { items: MyDevice[]; allPaused: boolean };

const OS_LABELS: Record<string, string> = { macos: "macOS", linux: "Linux", wsl2: "Windows (WSL2)" };
const SERVICE_LABELS: Record<string, string> = {
  launchd: "launchd",
  systemd: "systemd --user",
  "wsl-task": "Task Scheduler → WSL2",
  foreground: "foreground",
};

const text = (value: unknown): string | null => (typeof value === "string" && value ? value : null);
const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
const count = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);

export function readDevice(raw: unknown): MyDevice | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  const id = text(item.id);
  const name = text(item.name);
  if (!id || !name) return null;
  return {
    id,
    name,
    os: text(item.os) ?? "",
    paused: item.paused === true,
    connected: item.connected === true,
    runningJobs: count(item.running_jobs),
    maxParallelJobs: count(item.max_parallel_jobs),
    profiles: strings(item.profiles),
    seatLogin: item.seat_login === true,
    codexSeatLogin: item.codex_seat_login === true,
    needsLogin: item.needs_login === true,
    clientVersion: text(item.client_version),
    serviceKind: text(item.service_kind),
    folders: strings(item.folders),
    createdAt: text(item.created_at),
    lastSeenAt: text(item.last_seen_at),
  };
}

export function readMyDevices(raw: unknown): MyDevices | null {
  if (!raw || typeof raw !== "object" || !Array.isArray((raw as { items?: unknown }).items)) return null;
  const payload = raw as { items: unknown[]; all_paused?: unknown };
  return {
    items: payload.items.map(readDevice).filter((item): item is MyDevice => item !== null),
    allPaused: payload.all_paused === true,
  };
}

export const osLabel = (os: string) => OS_LABELS[os] ?? os;
export const serviceLabel = (kind: string | null) => (kind ? SERVICE_LABELS[kind] ?? kind : "not installed");

export type DeviceStatus = { label: string; tone: "running" | "active" | "neutral" | "attention"; offline: boolean };

export function deviceStatus(device: MyDevice): DeviceStatus {
  if (device.paused) return { label: "Paused", tone: "attention", offline: !device.connected };
  if (!device.connected && device.needsLogin) return { label: "Needs login", tone: "attention", offline: true };
  if (!device.connected) return { label: "Offline", tone: "neutral", offline: true };
  if (device.runningJobs > 0) {
    return { label: `${device.runningJobs} ${device.runningJobs === 1 ? "job" : "jobs"}`, tone: "running", offline: false };
  }
  return { label: "Online", tone: "active", offline: false };
}

export function relativeTime(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "never";
  const at = timeOf(iso);
  return at === null ? "unknown" : formatRelative(Math.min(at, now), "unknown", now);
}

const REFUSALS: Record<string, string> = {
  device_name_taken: "You already have a device with this name.",
  device_name_invalid: "Enter a name of up to 80 characters.",
  device_folders_platform_cannot_add: "Folders can only be added on the device itself.",
  device_not_found: "This device no longer exists.",
  device_revoked: "This device is revoked.",
};

export function deviceErrorText(error: unknown): string {
  const code = (error as { code?: unknown } | null)?.code;
  if (typeof code === "string" && REFUSALS[code]) return REFUSALS[code];
  return "The change could not be saved. Try again.";
}

export const CONNECT_COMMAND = 'octryx-claude device enable --name "<device name>" --folder <folder>';
