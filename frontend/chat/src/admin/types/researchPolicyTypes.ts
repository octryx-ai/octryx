export type ResearchPolicyDiagnostics = {
  status: "valid" | "invalid" | string;
  errors: Array<{ field: string; message: string }>;
  warnings: Array<{ field: string; message: string }>;
};

export type ResearchPolicyVersion = {
  id: string;
  profile_id: string;
  version: number;
  status: "draft" | "published" | "archived" | string;
  spec: Record<string, unknown>;
  notes: string;
  diagnostics: ResearchPolicyDiagnostics;
  published_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ResearchPolicyProfile = {
  id: string;
  key: string;
  name: string;
  description: string;
  lifecycle_status: string;
  is_active: boolean;
  latest_published_version_id: string | null;
  versions: ResearchPolicyVersion[];
};

export type ResearchPolicyListPayload = {
  profiles: ResearchPolicyProfile[];
  defaults: { default_profile_key: string };
  diagnostics: { status: string; invalid_version_count: number };
};

export type WorkspaceResearchPolicyPayload = {
  workspace: { id: string; name: string };
  assignment: {
    id: string;
    profile_version_id: string;
    assignment_status: string;
    assigned_by_user_id: string | null;
    assigned_at: string | null;
  } | null;
  effective_policy: {
    source: string;
    profile_key: string;
    profile_name: string;
    version: number;
    spec: Record<string, unknown>;
  };
  diagnostics: ResearchPolicyDiagnostics;
};
