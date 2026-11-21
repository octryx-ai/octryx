// A Workspace's device-run policy (backend api/routes/device_policy.py), read defensively.

export type DeviceRunsPolicy = {
  projectId: string;
  policyValid: boolean;
  enabled: boolean;
  allowedProfiles: string[];
  approvalTimeoutS: number;
  maxJobMinutes: number;
  allowJobEditScope: boolean;
  /** On the owner's own device the chat approval counts as the change confirmation (default on). */
  chatApprovalsConfirmChanges: boolean;
  staleTurnMinutes: number;
  platformEnabled: boolean;
  classification: string | null;
  classificationAllows: boolean;
  seatAllowed: boolean;
  cedarPreview: string;
  canEdit: boolean;
};

const num = (value: unknown, fallback: number) => (typeof value === "number" && Number.isFinite(value) ? value : fallback);

export function readDeviceRunsPolicy(raw: unknown): DeviceRunsPolicy | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  if (typeof item.project_id !== "string") return null;
  return {
    projectId: item.project_id,
    policyValid: item.policy_valid !== false,
    enabled: item.enabled === true,
    allowedProfiles: Array.isArray(item.allowed_profiles)
      ? item.allowed_profiles.filter((value): value is string => typeof value === "string") : ["governed"],
    approvalTimeoutS: num(item.approval_timeout_s, 300),
    maxJobMinutes: num(item.max_job_minutes, 60),
    allowJobEditScope: item.allow_job_edit_scope !== false,
    chatApprovalsConfirmChanges: item.chat_approvals_confirm_changes !== false,
    staleTurnMinutes: num(item.stale_turn_minutes, 10),
    platformEnabled: item.platform_enabled !== false,
    classification: typeof item.classification === "string" ? item.classification : null,
    classificationAllows: item.classification_allows !== false,
    seatAllowed: item.seat_allowed === true,
    cedarPreview: typeof item.cedar_preview === "string" ? item.cedar_preview : "",
    canEdit: item.can_edit === true,
  };
}

/** Why devices cannot be picked for this Workspace's chats; `null` when they can. */
export function deviceRunsBlocked(policy: DeviceRunsPolicy | null, workspaceName: string): string | null {
  if (!policy) return null;
  if (!policy.platformEnabled) return "Device runs are switched off on this platform.";
  if (!policy.policyValid || !policy.enabled) {
    return `Device runs are off for the Workspace “${workspaceName}”. A Workspace admin can turn them on in Agents → Policy.`;
  }
  if (!policy.classificationAllows) return "This Workspace's data classification does not allow device runs.";
  return null;
}

/** Seat is offered for a device job only where the Workspace allows it; the device needs a seat login too. */
export const workspaceAllowsSeat = (policy: DeviceRunsPolicy | null) =>
  !!policy && policy.allowedProfiles.includes("seat") && policy.seatAllowed;

export const minutes = (seconds: number) => `${Math.round(seconds / 60)} minutes`;
