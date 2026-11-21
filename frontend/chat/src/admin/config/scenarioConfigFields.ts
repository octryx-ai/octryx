// Scenario profile config fields the server does not accept. Turn preparation does not
// read the prompt text to match scenario profiles or pick tools; the server refuses a write
// carrying one of these keys (HTTP 422, `field_unsupported`). The admin panel never sends them.

export const UNSUPPORTED_SCENARIO_FIELDS = {
  match_config: ["keywords", "message_patterns"],
  planner_config: ["include_tools", "tool_allowlist", "blocked_tools"],
  execution_config: ["blocked_tools"],
} as const;

export type ScenarioConfigName = keyof typeof UNSUPPORTED_SCENARIO_FIELDS;

export const DEFAULT_SCENARIO_MATCH_CONFIG =
  '{\n  "route_reasons": [],\n  "required_domains": []\n}';
export const DEFAULT_SCENARIO_PLANNER_CONFIG =
  '{\n  "include_system_context": true,\n  "include_skills": true,\n  "include_recent_history": true,\n  "include_summary_context": true,\n  "token_budget": null\n}';
export const DEFAULT_SCENARIO_EXECUTION_CONFIG =
  '{\n  "required_domains": [],\n  "enforce_domain_coverage": false\n}';

/** A scenario config without its unsupported keys; the form never writes them back. */
export function withoutUnsupportedScenarioFields(
  name: ScenarioConfigName,
  config: Record<string, unknown>,
): Record<string, unknown> {
  const unsupported: readonly string[] = UNSUPPORTED_SCENARIO_FIELDS[name];
  return Object.fromEntries(
    Object.entries(config).filter(([key]) => !unsupported.includes(key)),
  );
}
