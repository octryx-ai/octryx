// A Mac job's pending tool approvals in a mobile chat: allow once, deny, or allow edits for the job.

import type { DeviceJob } from "../chat/devices/deviceJobTypes";
import { decide } from "./mobileApi";

export function JobApprovals({ job, pending, refresh }: {
  job: DeviceJob;
  pending: DeviceJob["approvals"];
  refresh: () => Promise<void>;
}) {
  return (
    <>
      {pending.map((approval) => (
        <section key={approval.id} className="m-approval">
          <b>Claude wants to run</b>
          <code>{approval.inputPreview || approval.tool}</code>
          <div className="m-buttons">
            <button
              type="button"
              className="m-primary"
              onClick={() =>
                void decide(job.id, approval.id, "allow_once").then(refresh)
              }
            >
              Allow once
            </button>
            <button
              type="button"
              onClick={() =>
                void decide(job.id, approval.id, "deny").then(refresh)
              }
            >
              Deny
            </button>
            {approval.canAllowJobEdits && (
              <button
                type="button"
                className="m-wide"
                onClick={() =>
                  void decide(job.id, approval.id, "allow_job_edits").then(
                    refresh,
                  )
                }
              >
                Allow for this job
              </button>
            )}
          </div>
        </section>
      ))}
    </>
  );
}
