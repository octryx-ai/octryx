// Admin › Platform › Devices: every user's devices from GET /api/v1/admin/devices, without their folders.
// Pure reading and labels, so the page and its tests share them.

export type AdminDevice = {
  id: string;
  name: string;
  os: string;
  status: string;
  ownerName: string;
  connected: boolean;
  paused: boolean;
  lastSeenAt: string | null;
  createdAt: string | null;
  revokedAt: string | null;
  clientVersion: string | null;
  serviceKind: string | null;
  profiles: string[];
  folderCount: number;
  runningJobs: number;
  maxParallelJobs: number;
};

const str = (value: unknown): string | null => (typeof value === "string" && value ? value : null);
const num = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);

export function readAdminDevices(raw: unknown): AdminDevice[] {
  const items = (raw as { items?: unknown } | null)?.items;
  if (!Array.isArray(items)) return [];
  return items.flatMap((entry) => {
    const item = (entry ?? {}) as Record<string, unknown>;
    if (typeof item.id !== "string" || typeof item.name !== "string") return [];
    return [{
      id: item.id,
      name: item.name,
      os: String(item.os ?? ""),
      status: String(item.status ?? ""),
      ownerName: str(item.owner_name) ?? "unknown user",
      connected: item.connected === true,
      paused: item.paused === true,
      lastSeenAt: str(item.last_seen_at),
      createdAt: str(item.created_at),
      revokedAt: str(item.revoked_at),
      clientVersion: str(item.client_version),
      serviceKind: str(item.service_kind),
      profiles: Array.isArray(item.profiles) ? item.profiles.filter((p): p is string => typeof p === "string") : [],
      folderCount: num(item.folder_count),
      runningJobs: num(item.running_jobs),
      maxParallelJobs: num(item.max_parallel_jobs),
    }];
  });
}

/** One state word per device; only revoked and offline carry colour (attention), online is neutral. */
export function adminDeviceState(device: AdminDevice): { label: string; tone: "neutral" | "attention" | "info" } {
  if (device.status !== "active") return { label: "Revoked", tone: "neutral" };
  if (device.paused) return { label: "Paused", tone: "attention" };
  if (device.connected) return device.runningJobs > 0 ? { label: "Working", tone: "info" } : { label: "Online", tone: "neutral" };
  return { label: "Offline", tone: "neutral" };
}

export const isRevocable = (device: AdminDevice) => device.status === "active";
