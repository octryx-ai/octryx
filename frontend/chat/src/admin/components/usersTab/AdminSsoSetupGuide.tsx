import { useState } from "react";

import "./identityPages.css";

// Route: backend/app/api/routes/auth.py (prefix /api/v1/auth, GET /oidc/callback).
export const OIDC_CALLBACK_PATH = "/api/v1/auth/oidc/callback";

function browserCallbackUrl(): string {
  if (typeof window === "undefined") return OIDC_CALLBACK_PATH;
  return `${window.location.origin}${OIDC_CALLBACK_PATH}`;
}

// The redirect URI to allow at the identity provider, with Copy. It is derived from the origin this browser uses;
// behind a proxy the identity provider may need the public origin instead, hence "as seen by this browser". The
// setup steps themselves are in help/admin/identityProviders.md.
export function OidcRedirectUri() {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const callbackUrl = browserCallbackUrl();

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(callbackUrl);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
    window.setTimeout(() => setCopyState("idle"), 2500);
  };

  return (
    <div className="admin-panel__field" data-testid="oidc-redirect-uri">
      <span>Redirect URI (as seen by this browser)</span>
      <div className="admin-users__callback">
        <code>{callbackUrl}</code>
        <button type="button" className="admin-panel__action-btn" onClick={() => void copy()}>
          {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy failed" : "Copy"}
        </button>
      </div>
    </div>
  );
}
