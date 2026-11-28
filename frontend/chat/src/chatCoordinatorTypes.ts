// Coordinator state contract and controls for a root session with delegated work.

export type CoordinatorMode =
  | "direct"
  | "worker_delegation"
  | "deterministic_workflow"
  | "unknown";

export type CoordinatorControlAction = "stop";

export type CoordinatorStateContract = {
  root_session_id: string;
  coordinator_mode: CoordinatorMode;
  aggregate_status: string;
  session_status: string;
  run_status: string;
  run_completion_reason?: string | null;
  child_session_ids: string[];
  delegated_session_ids: string[];
  delegation_ids: string[];
  progress_counts: Record<string, number>;
  progress_ratio?: number | null;
  synthesis_ready: boolean;
  can_stop: boolean;
};

export type CoordinatorControlResponse = {
  action: CoordinatorControlAction;
  contract: CoordinatorStateContract;
};
