// `device_job_event` from the session WebSocket handed to the live device-job block of that thread.
export const DEVICE_JOB_EVENT = "octryx:device-job-event";

export type DeviceJobEventDetail = { sessionId: string; payload: Record<string, unknown> };

export function emitDeviceJobEvent(sessionId: string, payload: Record<string, unknown>) {
  window.dispatchEvent(new CustomEvent<DeviceJobEventDetail>(DEVICE_JOB_EVENT, { detail: { sessionId, payload } }));
}
