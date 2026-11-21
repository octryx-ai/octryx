type ProviderRuntimeHintsProps = {
  provider: any;
};

// Runtime diagnostics of a local Ollama runtime: its health, profile and runner state as the backend reports them.
export function ProviderRuntimeHints({
  provider: p,
}: ProviderRuntimeHintsProps) {
  if (p.driver !== "ollama") return null;
  return (
    <div className="admin-panel__hint" style={{ marginBottom: "0.85rem" }}>
      Runtime diagnostics: status {p.health_status || "unknown"}
      {typeof p.config_json?.profile_home === "string" &&
      p.config_json.profile_home
        ? ` · profile home ${p.config_json.profile_home}`
        : ""}
      {typeof p.capabilities_json?.profile_has_files === "boolean"
        ? ` · profile ${
            p.capabilities_json.profile_has_files
              ? "has local state"
              : "is empty"
          }`
        : ""}
      {typeof p.capabilities_json?.runner_mode === "string" &&
      p.capabilities_json.runner_mode
        ? ` · runner ${String(p.capabilities_json.runner_mode)}`
        : ""}
      {typeof p.config_json?.local_runtime_strategy === "string" &&
      p.config_json.local_runtime_strategy
        ? ` · local ${String(p.config_json.local_runtime_strategy)}`
        : ""}
      {typeof p.capabilities_json?.auth_state === "string" &&
      p.capabilities_json.auth_state
        ? ` · auth ${p.capabilities_json.auth_state}`
        : ""}
      {p.last_health_error ? ` · ${p.last_health_error}` : ""}
    </div>
  );
}
