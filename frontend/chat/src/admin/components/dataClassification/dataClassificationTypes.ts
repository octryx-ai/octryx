// Data classification read models: levels, their effects, the Workspace and Instance default classification.

export type ClassificationEffects = {
  rerankerAllowed: boolean | null;
  rerankerState: RerankerState | null;
  rerankerReason: string | null;
  remoteEmbeddingsAllowed: boolean | null;
  remoteEmbeddingsReason: string | null;
  seatModeAllowed: boolean | null;
  seatModeReason: string | null;
  governedModels: string[] | null;
};

// F2 (judge-1191-1192): the reranker's runtime admission per level; `needs_configuration` is a runtime hold.
export type RerankerState = "ok" | "needs_configuration" | "denied";

export type ClassificationLevel = { value: string; label: string; description: string; effects: ClassificationEffects | null };

export type ClassificationSource = "workspace" | "instance_default" | "unset";

export type WorkspaceClassification = {
  effective: string | null;
  source: ClassificationSource;
  cleared: boolean;
  instanceDefault: string | null;
  levels: ClassificationLevel[];
  effects: ClassificationEffects | null;
  canEdit: boolean;
};

export type SeatMode = "forbidden" | "allowed";

export type InstanceDefault = {
  classification: string | null;
  environmentInEffect: boolean;
  environmentValue: string | null;
  levels: ClassificationLevel[];
  unclassifiedWorkspaces: number | null;
};
