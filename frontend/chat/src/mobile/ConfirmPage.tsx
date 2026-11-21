// /m/confirm?p=<pairing>: opened on the Mac by `octryx-claude mobile pair` in the person's browser, where they are
// signed in to the platform. Only this web session confirms a phone (never the Mac's gateway token): it shows the
// phone and its two-digit number and connects or declines.

import { useCallback, useEffect, useState } from "react";
import { OctryxMark } from "./OctryxMark";

type View = { state: string; match_number?: string; phone?: string };
type Step =
  | { kind: "loading" }
  | { kind: "signin" }
  | { kind: "view"; view: View }
  | { kind: "failed"; message: string };

const MESSAGES: Record<string, string> = {
  mobile_pairing_not_found: "This pairing does not exist or is not yours.",
  mobile_pairing_expired:
    "This pairing expired. Run octryx mobile pair again on your Mac.",
  mobile_pairing_used: "This pairing was already decided.",
  mobile_confirm_in_browser:
    "Open this page in your browser where you are signed in to the platform.",
};

async function call(
  path: string,
  init?: RequestInit,
): Promise<{ status: number; body: Record<string, unknown> }> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  const body = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  return { status: response.status, body };
}

export function ConfirmPage() {
  const pairingId = new URLSearchParams(window.location.search).get("p") ?? "";
  const [step, setStep] = useState<Step>({ kind: "loading" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { status, body } = await call(
      `/api/v1/mobile/pairings/${encodeURIComponent(pairingId)}`,
    );
    if (status === 401) return setStep({ kind: "signin" });
    if (status !== 200) {
      return setStep({
        kind: "failed",
        message:
          MESSAGES[String(body.reason)] ?? "The pairing could not be loaded.",
      });
    }
    setStep({ kind: "view", view: body as View });
  }, [pairingId]);

  useEffect(() => {
    if (!pairingId) {
      setStep({ kind: "failed", message: MESSAGES.mobile_pairing_not_found });
      return;
    }
    void load();
  }, [pairingId, load]);

  // Until the phone has scanned, keep looking.
  const waiting = step.kind === "view" && step.view.state === "pending";
  useEffect(() => {
    if (!waiting) return;
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [waiting, load]);

  const decide = async (approve: boolean) => {
    setBusy(true);
    const { status, body } = await call(
      `/api/v1/mobile/pairings/${encodeURIComponent(pairingId)}/confirm`,
      {
        method: "POST",
        body: JSON.stringify({ approve }),
      },
    );
    setBusy(false);
    if (status !== 200) {
      setStep({
        kind: "failed",
        message:
          MESSAGES[String(body.reason)] ?? "The decision did not go through.",
      });
      return;
    }
    setStep({ kind: "view", view: body as View });
  };

  const next = encodeURIComponent(`/m/confirm?p=${pairingId}`);
  return (
    <main className="m-center">
      <OctryxMark size={56} />
      <h1 className="m-title">Connect a phone</h1>
      {step.kind === "loading" && <p className="m-muted">Loading…</p>}
      {step.kind === "signin" && (
        <p>
          <a className="m-link" href={`/chat/login?next=${next}`}>
            Sign in to the platform
          </a>{" "}
          to confirm the phone.
        </p>
      )}
      {step.kind === "failed" && (
        <p className="m-error" role="alert">
          {step.message}
        </p>
      )}
      {step.kind === "view" && step.view.state === "pending" && (
        <p className="m-muted">Scan the QR code with your phone.</p>
      )}
      {step.kind === "view" && step.view.state === "scanned" && (
        <section className="m-card m-step">
          <span className="m-eyebrow">
            {step.view.phone ?? "A phone"} shows
          </span>
          <strong className="m-number">{step.view.match_number}</strong>
          <p className="m-muted">
            Connect only if your phone shows the same number.
          </p>
          <div className="m-buttons m-confirm-buttons">
            <button
              type="button"
              className="m-primary"
              disabled={busy}
              onClick={() => void decide(true)}
            >
              Connect
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void decide(false)}
            >
              Decline
            </button>
          </div>
        </section>
      )}
      {step.kind === "view" &&
        ["confirmed", "claimed"].includes(step.view.state) && (
          <p>
            Connected. On your iPhone: Share → Add to Home Screen, then open
            Octryx.
          </p>
        )}
      {step.kind === "view" && step.view.state === "denied" && (
        <p>Declined. The phone was not connected.</p>
      )}
      {step.kind === "view" && step.view.state === "expired" && (
        <p className="m-error">{MESSAGES.mobile_pairing_expired}</p>
      )}
    </main>
  );
}
