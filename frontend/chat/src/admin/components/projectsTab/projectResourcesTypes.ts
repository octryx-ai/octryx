export type RepositoryResource = {
  id: string;
  name: string;
  provider: string;
  repo_root: string;
  operation_policy: Record<string, boolean>;
};

export type RepositoryPolicyUpdate = {
  repository_id: string;
  operations: Record<string, boolean>;
};

export type KnowledgeBaseOption = {
  project_id: string;
  project_name: string;
};

export type KnowledgeMount = KnowledgeBaseOption & {
  source_project_id: string;
  source_project_name: string;
  mount_label: string;
  access: "read" | string;
};

export type KnowledgeMountUpdate = {
  source_project_id: string;
  mount_label: string;
};

export type ProjectResourcePayload = {
  repositories: RepositoryResource[];
  knowledge_base: KnowledgeBaseOption & { access: string };
  knowledge_access?: {
    mode: "default" | "limited" | "private" | string;
    default_workspace_access: boolean;
  };
  knowledge_mounts: KnowledgeMount[];
  available_knowledge_bases: KnowledgeBaseOption[];
  policy_keys: string[];
};
