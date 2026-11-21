// Remote device sessions: the caller's own devices (backend api/routes/devices.py). A refusal answers
// `{state, reason}` with a fixed code; it rides along on the thrown error as `code`.

export type DeviceRequestError = Error & {
  status: number;
  code: string | null;
};

async function deviceJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
    },
    ...init,
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const reason = (payload as { reason?: unknown } | null)?.reason;
    const code =
      typeof reason === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(reason)
        ? reason
        : null;
    const path = (payload as { path?: unknown } | null)?.path;
    throw Object.assign(
      new Error(code ?? (response.statusText || "Request failed")),
      { status: response.status, code, path: typeof path === "string" ? path : null },
    );
  }
  return payload as T;
}

const DEVICES = "/api/v1/devices";
const devicePath = (deviceId: string) =>
  `${DEVICES}/${encodeURIComponent(deviceId)}`;

export function loadMyDevices(): Promise<unknown> {
  return deviceJson<unknown>(DEVICES);
}

export function updateDevice(
  deviceId: string,
  patch: { name?: string; folders?: string[]; paused?: boolean },
) {
  return deviceJson<unknown>(devicePath(deviceId), {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function revokeDevice(deviceId: string) {
  return deviceJson<unknown>(`${devicePath(deviceId)}/revoke`, {
    method: "POST",
  });
}

export function pauseAllDevices(paused: boolean) {
  return deviceJson<unknown>(`${DEVICES}/pause`, {
    method: "PUT",
    body: JSON.stringify({ paused }),
  });
}

const deviceRunsPath = (projectId: string) =>
  `/api/v1/workspaces/${encodeURIComponent(projectId)}/agent-gateway/device-runs`;

export function loadDeviceRunsPolicy(projectId: string): Promise<unknown> {
  return deviceJson<unknown>(deviceRunsPath(projectId));
}

/** The Model pill's rows for a device job (the profile's `/model` rows in this Workspace). */
export function loadDeviceRunModels(
  projectId: string,
  profile: string,
  deviceId: string,
): Promise<unknown> {
  const query = new URLSearchParams({ profile, device_id: deviceId });
  return deviceJson<unknown>(
    `${deviceRunsPath(projectId)}/models?${query.toString()}`,
  );
}

export function saveDeviceRunsPolicy(
  projectId: string,
  patch: Record<string, unknown>,
): Promise<unknown> {
  return deviceJson<unknown>(deviceRunsPath(projectId), {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

/** Applies a refused tool call's `remedy` (Workspace admins/owners); answers like GET device-runs. */
export function applyDeviceRunsRemedy(
  projectId: string,
  body: Record<string, unknown>,
): Promise<unknown> {
  return deviceJson<unknown>(`${deviceRunsPath(projectId)}/remedy`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function savePlatformDeviceRuns(enabled: boolean): Promise<unknown> {
  return deviceJson<unknown>("/api/v1/admin/device-runs", {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

export function loadAdminDevices(): Promise<unknown> {
  return deviceJson<unknown>("/api/v1/admin/devices");
}

export function adminRevokeDevice(
  deviceId: string,
  reason: string,
): Promise<unknown> {
  return deviceJson<unknown>(
    `/api/v1/admin/devices/${encodeURIComponent(deviceId)}/revoke`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );
}

// Octryx Mobile: the platform's device login validity and the caller's paired phones.
export function loadLoginValidity(): Promise<unknown> {
  return deviceJson<unknown>("/api/v1/admin/devices/login-validity");
}

export function saveLoginValidity(validity: string): Promise<unknown> {
  return deviceJson<unknown>("/api/v1/admin/devices/login-validity", {
    method: "PUT",
    body: JSON.stringify({ validity }),
  });
}

export function loadMyPhones(): Promise<unknown> {
  return deviceJson<unknown>("/api/v1/mobile/devices");
}

export function revokePhone(phoneId: string): Promise<unknown> {
  return deviceJson<unknown>(
    `/api/v1/mobile/devices/${encodeURIComponent(phoneId)}/revoke`,
    { method: "POST" },
  );
}
