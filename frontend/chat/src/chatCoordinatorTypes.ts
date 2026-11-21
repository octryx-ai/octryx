// Coordinator state contract and controls for a root session with delegated work.

export type CoordinatorMode =
  | "direct"
  | "sub_agent_group"
  | "worker_delegation"
  | "deterministic_workflow"
  | "unknown";

export type CoordinatorControlAction = "continue" | "stop";

export type CoordinatorStateContract = {
  root_session_id: string;
  coordinator_mode: CoordinatorMode;
  aggregate_status: string;
  session_status: string;
  run_status: string;
  run_completion_reason?: string | null;
  child_session_ids: string[];
  delegated_session_ids: string[];
  sub_agent_group_id?: string | null;
  delegation_ids: string[];
  progress_counts: Record<string, number>;
  progress_ratio?: number | null;
  document_flow?: Record<string, string | number | boolean | null> | null;
  synthesis_ready: boolean;
  can_continue: boolean;
  can_stop: boolean;
};

export type CoordinatorControlResponse = {
  action: CoordinatorControlAction;
  contract: CoordinatorStateContract;
};
