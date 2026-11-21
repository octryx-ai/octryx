import { useCallback, useEffect, useState } from "react";

import { loadDeviceRunsPolicy, saveDeviceRunsPolicy, savePlatformDeviceRuns } from "./devicesApi";
import { minutes, readDeviceRunsPolicy, type DeviceRunsPolicy } from "./deviceRunsPolicyModel";
import "./devices.css";

// The Workspace setting "Run requests on members' own devices" (on by default) with its profile and time limits,
// the fixed owner-only approvals, and the platform switch. Edited in Settings → Workspace → Coding tools & devices;
// chat Agents → Policy shows it read-only with "Edit in Settings".
const TIMEOUTS = [120, 300, 900];
const JOB_MINUTES = [30, 60, 240];
const STALE_MINUTES = [5, 10, 30];

function Toggle({ on, label, disabled, onChange }: {
  on: boolean;
  label: string;
  disabled?: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <span className={`toggle-switch ${on ? "toggle-switch--on" : ""}`} role="switch" aria-checked={on} aria-label={label}
      aria-disabled={disabled} tabIndex={disabled ? -1 : 0}
      onClick={() => { if (!disabled) onChange(!on); }}
      onKeyDown={(event) => {
        if (!disabled && (event.key === " " || event.key === "Enter")) {
          event.preventDefault();
          onChange(!on);
        }
      }} />
  );
}
type Save = (patch: Record<string, unknown>) => Promise<void>;

function DeviceRunsLimits({ policy, fieldsDisabled, save }: { policy: DeviceRunsPolicy; fieldsDisabled: boolean; save: Save }) {
  return (
    <div className="device-grid2">
      <label className="admin-panel__field">
        <span>Allowed profiles on devices</span>
        <select disabled={fieldsDisabled} value={policy.allowedProfiles.includes("seat") ? "both" : "governed"}
          onChange={(event) => void save({ allowed_profiles: event.target.value === "both" ? ["governed", "seat"] : ["governed"] })}>
          <option value="governed">governed only</option>
          <option value="both">governed and seat (seat only where the Workspace's seat rules allow it)</option>
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Approval timeout</span>
        <select disabled={fieldsDisabled} value={policy.approvalTimeoutS}
          onChange={(event) => void save({ approval_timeout_s: Number(event.target.value) })}>
          {[...new Set([...TIMEOUTS, policy.approvalTimeoutS])].map((value) => (
            <option key={value} value={value}>{minutes(value)} → deny</option>
          ))}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Longest job</span>
        <select disabled={fieldsDisabled} value={policy.maxJobMinutes}
          onChange={(event) => void save({ max_job_minutes: Number(event.target.value) })}>
          {[...new Set([...JOB_MINUTES, policy.maxJobMinutes])].map((value) => (
            <option key={value} value={value}>{value} minutes</option>
          ))}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>A turn without device events ends after</span>
        <select disabled={fieldsDisabled} value={policy.staleTurnMinutes}
          onChange={(event) => void save({ stale_turn_minutes: Number(event.target.value) })}>
          {[...new Set([...STALE_MINUTES, policy.staleTurnMinutes])].map((value) => (
            <option key={value} value={value}>{value} minutes → interrupted</option>
          ))}
        </select>
      </label>
    </div>
  );
}

function DeviceRunsApprovals({ policy, fieldsDisabled, save }: { policy: DeviceRunsPolicy; fieldsDisabled: boolean; save: Save }) {
  return (
    <>
      <div className="device-setting">
        <div><b>Who answers tool approvals</b>
          <p>The device owner, in the chat that started the job. Fixed — no delegation, no admin override.</p></div>
        <span className="work-badge work-badge--neutral">Owner only</span>
      </div>
      <div className="device-setting">
        <div><b>Allow “Allow edits for this job”</b>
          <p>Lets the owner approve file edits inside the job's folder once per job instead of per edit. Shell commands
            are always asked per command unless a Workspace rule allows them.</p></div>
        <Toggle on={policy.allowJobEditScope} label="Allow edits for this job" disabled={fieldsDisabled}
          onChange={(next) => void save({ allow_job_edit_scope: next })} />
      </div>
      <div className="device-setting">
        <div><b>Chat approvals on own devices count as change confirmation</b>
          <p>On the owner's own device, the owner's approval in the chat (Allow once / Allow edits for this job)
            confirms a change; every such write is audited with the owner as approver. Off: changes need a confirmed
            change workflow (workflow_catalog, then workflow_select), as in any governed session.</p></div>
        <Toggle on={policy.chatApprovalsConfirmChanges} label="Chat approvals on own devices count as change confirmation"
          disabled={fieldsDisabled} onChange={(next) => void save({ chat_approvals_confirm_changes: next })} />
      </div>
      <div className="device-setting">
        <div><b>Data classification and model routing</b>
          <p>{policy.classification ? `This Workspace is ${policy.classification}. ` : ""}
            {policy.classificationAllows ? "The classification matrix allows device runs; " : "The classification matrix does not allow device runs; "}
            every model call of a device job is still routed by the matrix's model rules, and seat only where the
            Workspace's seat rules allow it.</p></div>
        <span className={`work-badge ${policy.classificationAllows ? "work-badge--active" : "work-badge--danger"}`}>
          {policy.classificationAllows ? "Allowed" : "Not allowed"}
        </span>
      </div>
      <details>
        <summary className="device-summary">Generated Cedar (read-only)</summary>
        <pre className="device-pre">{`// generated from these settings — edit them here, not in the policy editor\n${policy.cedarPreview}`}</pre>
      </details>
    </>
  );
}

function PlatformSwitches({ policy, isPlatformAdmin, readOnly, switchPlatform }: {
  policy: DeviceRunsPolicy;
  isPlatformAdmin: boolean;
  readOnly: boolean;
  switchPlatform: (enabled: boolean) => Promise<void>;
}) {
  return (
    <section className="admin-panel__card" aria-label="Platform switches">
      <div className="admin-panel__section-header"><span>Platform switches</span></div>
      <div className="device-setting">
        <div><b>Device runs on this platform</b>
          <p>Platform admin kill switch. Off stops every running device job within seconds.</p></div>
        <span className="device-row">
          <span className={`work-badge ${policy.platformEnabled ? "work-badge--active" : "work-badge--danger"}`}>
            {policy.platformEnabled ? "Enabled" : "Off"}
          </span>
          {isPlatformAdmin && !readOnly ? (
            <Toggle on={policy.platformEnabled} label="Device runs on this platform"
              onChange={(next) => void switchPlatform(next)} />
          ) : null}
        </span>
      </div>
      <div className="device-setting">
        <div><b>Custom Cedar policies for run_on_device</b>
          <p>Can only block (forbid), for example no device runs outside office hours.</p></div>
        <span className="work-badge work-badge--neutral">Forbid only</span>
      </div>
    </section>
  );
}

// The Workspace's device-run policy with its save and the platform switch; a failure is one problem line.
function useDeviceRunsPolicy(projectId: string) {
  const [policy, setPolicy] = useState<DeviceRunsPolicy | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPolicy(readDeviceRunsPolicy(await loadDeviceRunsPolicy(projectId)));
      setProblem(null);
    } catch {
      setProblem("The device-run policy could not be loaded.");
    }
  }, [projectId]);

  useEffect(() => {
    setPolicy(null);
    void load();
  }, [load]);

  const save = async (patch: Record<string, unknown>) => {
    try {
      setPolicy(readDeviceRunsPolicy(await saveDeviceRunsPolicy(projectId, patch)));
      setProblem(null);
    } catch {
      setProblem("The change could not be saved.");
    }
  };

  const switchPlatform = async (enabled: boolean) => {
    try {
      await savePlatformDeviceRuns(enabled);
      await load();
    } catch {
      setProblem("The platform switch could not be changed.");
    }
  };

  return { policy, problem, save, switchPlatform };
}

export function DeviceRunsPolicyCard({ projectId, isPlatformAdmin = false, readOnly = false, onEditInSettings }: {
  projectId: string;
  isPlatformAdmin?: boolean;
  readOnly?: boolean;
  onEditInSettings?: () => void;
}) {
  const { policy, problem, save, switchPlatform } = useDeviceRunsPolicy(projectId);

  if (!policy) {
    return problem ? <p className="work-area__error" role="alert">{problem}</p> : null;
  }
  const editable = !readOnly && policy.canEdit && policy.policyValid;
  const fieldsDisabled = !editable || !policy.enabled;
  return (
    <>
      <section className="admin-panel__card" aria-label="Device runs">
        <DeviceRunsHeader policy={policy} editable={editable} save={save} />
        {readOnly && onEditInSettings ? (
          <p className="device-muted">
            <button type="button" className="admin-panel__action-btn" data-testid="device-runs-edit-in-settings" onClick={onEditInSettings}>
              Edit in Settings
            </button>
          </p>
        ) : null}
        {!policy.policyValid ? (
          <p className="device-warn">The Workspace's agent gateway policy is invalid, so device runs stay off.</p>
        ) : null}
        <div className={`admin-panel__stack ${fieldsDisabled ? "device-fields--off" : ""}`}>
          <DeviceRunsLimits policy={policy} fieldsDisabled={fieldsDisabled} save={save} />
          <DeviceRunsApprovals policy={policy} fieldsDisabled={fieldsDisabled} save={save} />
        </div>
      </section>
      <PlatformSwitches policy={policy} isPlatformAdmin={isPlatformAdmin} readOnly={readOnly} switchPlatform={switchPlatform} />
    </>
  );
}

function DeviceRunsHeader({ policy, editable, save }: { policy: DeviceRunsPolicy; editable: boolean; save: Save }) {
  return (
    <div className="device-between">
      <div>
        <div className="device-card-title">Run requests on members' own devices</div>
        <div className="device-muted">
          Members may send chat requests of this Workspace to their own connected octryx-claude devices. On by default.
        </div>
      </div>
      <div className="device-row">
        <span className={`work-badge ${policy.enabled ? "work-badge--active" : "work-badge--neutral"}`}>
          {policy.enabled ? "On" : "Off"}
        </span>
        <Toggle on={policy.enabled} label="Run requests on members' own devices" disabled={!editable}
          onChange={(next) => void save({ enabled: next })} />
      </div>
    </div>
  );
}
