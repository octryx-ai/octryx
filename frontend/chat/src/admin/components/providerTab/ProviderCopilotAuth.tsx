import type { ProviderTabCtx } from "./types";

type ProviderCopilotAuthProps = {
  ctx: ProviderTabCtx;
  provider: any;
};
// The device code and where to enter it, while GitHub waits for the person.
function CopilotPendingCode({ ctx }: { ctx: ProviderTabCtx }) {
  const { copilotFlow, handleCopilotDisconnect } = ctx;
  return (
    <div className="copilot-device-flow__pending">
      <div className="copilot-device-flow__code">
        {copilotFlow.userCode}
      </div>
      <div className="copilot-device-flow__instructions">
        Visit{" "}
        <a
          href={copilotFlow.verificationUri}
          target="_blank"
          rel="noopener noreferrer"
        >
          {copilotFlow.verificationUri}
        </a>{" "}
        and enter the code above.
      </div>
      <div className="copilot-device-flow__spinner">
        Waiting for authorization…
      </div>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={handleCopilotDisconnect}
      >
        Cancel
      </button>
    </div>
  );
}

// The running device flow: connected, failed (retry or cancel) or the code to enter at GitHub.
function CopilotDeviceFlow({ ctx, providerId }: { ctx: ProviderTabCtx; providerId: string }) {
  const { copilotFlow, handleCopilotConnect, handleCopilotDisconnect } = ctx;
  return (
    <div className="copilot-device-flow">
      {copilotFlow.status === "connected" ? (
        <div className="copilot-device-flow__connected">
          <svg
            viewBox="0 0 20 20"
            aria-hidden="true"
            className="copilot-device-flow__check"
          >
            <path d="M4 10l5 5 7-7" />
          </svg>
          Connected as <strong>{copilotFlow.login || "GitHub user"}</strong>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={handleCopilotDisconnect}
          >
            Dismiss
          </button>
        </div>
      ) : copilotFlow.status === "failed" ? (
        <div className="copilot-device-flow__error">
          Login failed: {copilotFlow.error || "unknown error"}
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => void handleCopilotConnect(providerId)}
          >
            Retry
          </button>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={handleCopilotDisconnect}
          >
            Cancel
          </button>
        </div>
      ) : (
        <CopilotPendingCode ctx={ctx} />
      )}
    </div>
  );
}

// No flow running: the connected account (or "Not connected") and Connect / Reconnect with GitHub.
function CopilotAccount({ ctx, provider: p }: ProviderCopilotAuthProps) {
  const { handleCopilotConnect } = ctx;
  return (
    <div
      className="provider-card__key-display"
      style={{ flexWrap: "wrap", gap: "0.5rem" }}
    >
      {p.auth_login ? (
        <div className="copilot-device-flow__connected" style={{ flex: 1 }}>
          <svg
            viewBox="0 0 20 20"
            aria-hidden="true"
            className="copilot-device-flow__check"
          >
            <path d="M4 10l5 5 7-7" />
          </svg>
          {p.auth_name && <span>{p.auth_name}</span>}
          <span>·</span>
          <span>@{p.auth_login}</span>
          <span>·</span>
          <a
            href={p.auth_host || "https://github.com"}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--status-running-ink)", textDecoration: "none" }}
          >
            {p.auth_host || "https://github.com"}
          </a>
        </div>
      ) : (
        <span className="provider-card__key-masked">Not connected</span>
      )}
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--github"
        onClick={() => void handleCopilotConnect(p.id)}
      >
        <svg
          viewBox="0 0 20 20"
          aria-hidden="true"
          style={{
            width: "1rem",
            height: "1rem",
            marginRight: "0.35rem",
            verticalAlign: "middle",
          }}
        >
          <path
            fillRule="evenodd"
            d="M10 0C4.477 0 0 4.477 0 10c0 4.418 2.865 8.166 6.84 9.49.5.09.682-.218.682-.482 0-.237-.009-.866-.013-1.7-2.782.604-3.369-1.34-3.369-1.34-.454-1.157-1.11-1.465-1.11-1.465-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.09-.647.35-1.087.636-1.338-2.22-.253-4.555-1.11-4.555-4.944 0-1.091.39-1.984 1.03-2.682-.104-.254-.447-1.27.097-2.646 0 0 .84-.269 2.75 1.025A9.578 9.578 0 0110 4.844a9.59 9.59 0 012.504.337c1.909-1.294 2.748-1.025 2.748-1.025.546 1.376.202 2.392.1 2.646.64.698 1.028 1.59 1.028 2.682 0 3.841-2.337 4.687-4.565 4.935.359.31.678.919.678 1.852 0 1.336-.012 2.415-.012 2.742 0 .267.18.577.688.48C17.138 18.163 20 14.418 20 10c0-5.523-4.477-10-10-10z"
          />
        </svg>
        {p.auth_login ? "Reconnect with GitHub" : "Connect with GitHub"}
      </button>
    </div>
  );
}

export function ProviderCopilotAuth({
  ctx,
  provider: p,
}: ProviderCopilotAuthProps) {
  const { copilotFlow } = ctx;

  return (
    <div className="provider-card__key-row">
      <span className="provider-card__key-label">GitHub Auth</span>
      {copilotFlow?.providerId === p.id ? (
        <CopilotDeviceFlow ctx={ctx} providerId={p.id} />
      ) : (
        <CopilotAccount ctx={ctx} provider={p} />
      )}
    </div>
  );
}
