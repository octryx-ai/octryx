// The per-Workspace intake overview, as the server sends it
// (`GET /api/v1/secure-work/workspaces/{id}/intake`).

export type IntakeConnection = { id: string; name: string; scope: string };

export type IntakeWorkState = "not_a_work_source" | "no_connection" | "no_intake" | "set_up";

export type IntakeSource = {
  kind: string;
  label: string;
  work_capable: boolean;
  connections: IntakeConnection[];
  knowledge: { sources: number; last_synced_at: string | null } | null;
  work: { intakes: number; active: number; items: number; last_run_at: string | null; last_run_status: string | null } | null;
  work_state: IntakeWorkState;
};

export type IntakeSchedule = { preset: string; cron: string | null };

export type IntakeSummary = {
  id: string;
  name: string;
  source_type: string;
  is_active: boolean;
  connection: { id: string; name: string; available: boolean };
  what: Record<string, string[] | boolean | string | null>;
  schedule: IntakeSchedule;
  automation_mode: string | null;
  automation_labels: string[];
  items: number;
  last_run_at: string | null;
  last_run_status: string | null;
  /** The intake's own write-back mode (backend); null: it follows the Workspace workflow. */
  sync_mode: string | null;
  /** The mode in force: the own one, else the workflow's; null when neither is set (nothing is written). */
  effective_sync_mode: string | null;
  /** The Workspace workflow's own mode (backend); null when the workflow sets none. */
  workflow_sync_mode: string | null;
};

export type IntakeOverview = { project_id: string; sources: IntakeSource[]; intakes: IntakeSummary[] };
