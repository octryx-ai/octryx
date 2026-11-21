import { useState } from "react";

import { triggerUrl, type InboundWebhook } from "./inboundWebhookModel";

// The trigger URL (copy) and, right after create or rotate, the signing secret once.
export function InboundSecretFields({ webhook }: { webhook: InboundWebhook }) {
  const [copied, setCopied] = useState<string | null>(null);
  const url = triggerUrl(
    webhook.trigger_path,
    typeof window === "undefined" ? "" : window.location.origin,
  );
  const copy = (label: string, value: string) => {
    void navigator.clipboard?.writeText(value);
    setCopied(label);
  };
  if (webhook.polled) {
    return (
      <p className="automation-muted">
        Changes are read through the connector; this source needs no URL.
      </p>
    );
  }
  return (
    <>
      <div className="admin-panel__field">
        <span>Webhook URL</span>
        <div className="automation-copy">
          <code data-testid="inbound-url">{url}</code>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => copy("url", url)}
          >
            {copied === "url" ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      {webhook.secret ? (
        <div className="admin-panel__field">
          <span>Signing secret</span>
          <div className="automation-copy">
            <code data-testid="inbound-secret">{webhook.secret}</code>
            <button
              type="button"
              className="admin-panel__action-btn"
              onClick={() => copy("secret", webhook.secret || "")}
            >
              {copied === "secret" ? "Copied" : "Copy"}
            </button>
          </div>
          <small className="automation-muted">
            Shown only now. Sign each call with X-Webhook-Timestamp (Unix
            seconds) and X-Webhook-Signature: sha256=HMAC of
            &quot;timestamp.body&quot;. Tools that can&apos;t sign a timestamp
            need the setting in the webhook&apos;s drawer. If you lose it,
            rotate it.
          </small>
        </div>
      ) : null}
    </>
  );
}
