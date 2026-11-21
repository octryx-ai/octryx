// Scenario form: pure parsers of the stored match, planner and execution config JSON into form state.

// The match settings of a scenario from its stored JSON (empty lists when it does not parse).
export function parseScenarioMatchConfig(scenarioMatchConfig: string): {
  route_reasons: string[];
  required_domains: string[];
} {
  try {
    const cfg = JSON.parse(scenarioMatchConfig || "{}") as {
      route_reasons?: unknown[];
      route_reason?: unknown;
      required_domains?: unknown[];
    };
    const strList = (arr: unknown[]) =>
      (arr || []).map(String).filter(Boolean);
    return {
      route_reasons: strList(
        cfg.route_reasons || (cfg.route_reason ? [cfg.route_reason] : []),
      ),
      required_domains: strList(cfg.required_domains || []),
    };
  } catch {
    return {
      route_reasons: [],
      required_domains: [],
    };
  }
}

// The planner settings of a scenario from its stored JSON (all off and empty when it does not parse).
export function parseScenarioPlannerConfig(scenarioPlannerConfig: string): {
  include_skills: boolean;
  include_system_context: boolean;
  include_recent_history: boolean;
  include_summary_context: boolean;
  token_budget: string;
  recent_history_limit: string;
  system_prompt_variant: string;
} {
  try {
    const cfg = JSON.parse(scenarioPlannerConfig || "{}") as Record<
      string,
      unknown
    >;
    return {
      include_skills: Boolean(cfg.include_skills),
      include_system_context: Boolean(cfg.include_system_context),
      include_recent_history: Boolean(cfg.include_recent_history),
      include_summary_context: Boolean(cfg.include_summary_context),
      token_budget: String(cfg.token_budget ?? ""),
      recent_history_limit: String(cfg.recent_history_limit ?? ""),
      system_prompt_variant: String(cfg.system_prompt_variant ?? ""),
    };
  } catch {
    return {
      include_skills: false,
      include_system_context: false,
      include_recent_history: false,
      include_summary_context: false,
      token_budget: "",
      recent_history_limit: "",
      system_prompt_variant: "",
    };
  }
}

// The execution settings of a scenario from its stored JSON (empty when it does not parse).
export function parseScenarioExecutionConfig(scenarioExecutionConfig: string): {
  required_domains: string[];
  enforce_domain_coverage: boolean;
} {
  try {
    const cfg = JSON.parse(scenarioExecutionConfig || "{}") as Record<
      string,
      unknown
    >;
    const strList = (v: unknown) =>
      Array.isArray(v) ? (v as unknown[]).map(String).filter(Boolean) : [];
    return {
      required_domains: strList(cfg.required_domains),
      enforce_domain_coverage: Boolean(cfg.enforce_domain_coverage),
    };
  } catch {
    return {
      required_domains: [],
      enforce_domain_coverage: false,
    };
  }
}
