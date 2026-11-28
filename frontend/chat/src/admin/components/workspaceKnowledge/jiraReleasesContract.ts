export type ReleaseSectionBlock = { title: string; issue_types: string[]; labels: string[] };

// A Jira project without an entry has no release sync.
export type ReleasesBlock = {
  products: Record<string, string>;
  version_name_prefixes: string[];
  sections: ReleaseSectionBlock[];
  blocker_priorities: string[];
};

export type ReleaseSyncState = {
  state: "off" | "active" | "needs_configuration";
  reason?: string;
  products?: Record<string, string>;
};

export const RELEASE_CODE_TEXT: Record<string, string> = {
  release_block_invalid: "the releases block has an unknown key or shape",
  release_project_key_invalid: "not a Jira project key (uppercase letters, digits, underscore)",
  release_project_not_in_scope: "the project is not one of this connector's project keys",
  release_product_invalid: "not a product key (lowercase letters, digits, dashes; one product)",
  release_list_invalid: "must be a list of values",
  release_too_many_values: "too many values for this list",
  release_value_invalid: "a value is empty or contains control characters",
  release_value_too_long: "a value is longer than the server allows",
  release_section_invalid: "the section has an unknown key or shape",
  release_section_title_invalid: "the section title is empty or too long",
  release_section_without_match: "a section needs at least one issue type or label",
  release_product_not_configured: "no project is mapped to a product yet, so no release is synced",
  client_required: "required",
  client_invalid_format: "invalid format",
  client_duplicate: "already in the list",
};

export function releaseCodeText(code: string): string {
  return RELEASE_CODE_TEXT[code] ?? code.replace(/_/g, " ");
}
