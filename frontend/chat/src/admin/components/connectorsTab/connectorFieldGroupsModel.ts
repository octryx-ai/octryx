// The groups of a connector card's generic fields (delivery 5): where a preset field is shown. Pure.
//
// The presets name their fields by one convention (`<connector>_<what>`), so the group follows the field's role:
// secrets and sign-in fields are Authentication, the address of the system is Connection, allowlists are Scope,
// everything else (timeouts, limits, import settings) is Settings. Only the place on the card depends on it.

export type FieldGroup = "connection" | "authentication" | "scope" | "settings";

export const GROUP_ORDER: FieldGroup[] = ["connection", "authentication", "scope", "settings"];
export const GROUP_TITLES: Record<FieldGroup, string> = {
  connection: "Connection",
  authentication: "Authentication",
  scope: "Scope",
  settings: "Settings",
};

const CONNECTION = /(_url|_host|_hostname|_port|_base_url|_endpoint|_region|_instance|_cluster|_context|_path|_database|_project_id|_account_id)$/;
const AUTHENTICATION = /(_username|_user|_email|_password|_token|_secret|_api_key|_key_id|_auth_mode|_auth|_client_id|_client_secret|_tenant_id|_token_url|_oidc_[a-z_]+|_role_arn|_principal)$/;
const SCOPE = /(_allowed_[a-z_]+|_spaces|_pages|_repos|_repositories|_projects|_namespaces|_tables|_subscription_ids|_mailboxes)$/;

export function fieldGroup(field: string, secretFields: string[] = []): FieldGroup {
  if (secretFields.includes(field) || AUTHENTICATION.test(field)) return "authentication";
  if (SCOPE.test(field)) return "scope";
  if (CONNECTION.test(field)) return "connection";
  return "settings";
}

/** The fields per group, in card order; groups without fields are left out. */
export function groupedFields(fields: string[], secretFields: string[] = []): Array<{ group: FieldGroup; fields: string[] }> {
  return GROUP_ORDER.map((group) => ({ group, fields: fields.filter((field) => fieldGroup(field, secretFields) === group) }))
    .filter((entry) => entry.fields.length > 0);
}

/** A field name in words without its connector prefix: "confluence_allowed_spaces" → "Allowed spaces". */
const ACRONYMS = new Set(["url", "api", "id", "ids", "oidc", "tls", "arn", "jql", "sql", "ssh", "kv", "aws", "gcp"]);

export function fieldLabel(toolName: string, field: string): string {
  const prefix = `${toolName}_`;
  const bare = field.startsWith(prefix) ? field.slice(prefix.length) : field;
  const words = bare.split("_").filter(Boolean).map((word) => (ACRONYMS.has(word) ? word.toUpperCase() : word));
  if (!words.length) return field;
  return [words[0].charAt(0).toUpperCase() + words[0].slice(1), ...words.slice(1)].join(" ");
}
