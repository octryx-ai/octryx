import { RuntimeField, RuntimeSettingsGroup } from "./RuntimeSettingsGroup";
import type { RuntimeTabCtx } from "./types";

// Where shell, CLI, kubectl and saved-script commands run.
export function RuntimeExecutionIsolationFields({ ctx }: { ctx: RuntimeTabCtx }) {
  const {
    runtimeExecutionAllowHostFallback,
    runtimeExecutionDockerImageDraft,
    runtimeExecutionDockerNetworkDraft,
    runtimeExecutionProviderDraft,
    setRuntimeExecutionAllowHostFallback,
    setRuntimeExecutionDockerImageDraft,
    setRuntimeExecutionDockerNetworkDraft,
    setRuntimeExecutionProviderDraft,
  } = ctx;
  const docker = runtimeExecutionProviderDraft === "docker";

  return (
    <RuntimeSettingsGroup
      title="Isolation"
      purpose="Where shell, CLI, kubectl and saved-script commands run, and what they may reach."
    >
      <div className="admin-form-grid">
        <RuntimeField id="runtime-exec-provider" label="Run commands on">
          <select
            id="runtime-exec-provider"
            className="admin-panel__input"
            value={runtimeExecutionProviderDraft}
            onChange={(e) => setRuntimeExecutionProviderDraft(e.target.value as "host" | "docker")}
          >
            <option value="host">Host (no container)</option>
            <option value="docker">Docker container</option>
          </select>
        </RuntimeField>
        <RuntimeField
          id="runtime-exec-image"
          label="Docker image"
          help={docker ? "Image each command container starts from." : "Used only when commands run in Docker."}
        >
          <input
            id="runtime-exec-image"
            className="admin-panel__input"
            value={runtimeExecutionDockerImageDraft}
            onChange={(e) => setRuntimeExecutionDockerImageDraft(e.target.value)}
            placeholder="python:3.11-slim"
          />
        </RuntimeField>
        <RuntimeField
          id="runtime-exec-network"
          label="Container network"
        >
          <select
            id="runtime-exec-network"
            className="admin-panel__input"
            value={runtimeExecutionDockerNetworkDraft}
            onChange={(e) =>
              setRuntimeExecutionDockerNetworkDraft(e.target.value as "none" | "bridge" | "host")
            }
          >
            <option value="none">No network</option>
            <option value="bridge">Own network (bridge)</option>
            <option value="host">The server's network (host)</option>
          </select>
        </RuntimeField>
        <label className="admin-panel__checkbox">
          <input
            type="checkbox"
            checked={runtimeExecutionAllowHostFallback}
            onChange={(e) => setRuntimeExecutionAllowHostFallback(e.target.checked)}
          />
          <span>Run on the host when Docker is unavailable</span>
        </label>
      </div>
    </RuntimeSettingsGroup>
  );
}
