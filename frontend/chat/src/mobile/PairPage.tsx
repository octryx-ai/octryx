// /m/pair#c=<code>: the page the phone's camera opens from the Mac's QR code. It redeems the code once, shows the
// two-digit number the Mac shows too, waits for the confirmation on the Mac, then hands the claim to the Home
// Screen app (the address the app will start from) and shows it as a code to type, in case iOS does not.

import { useEffect, useState } from "react";
import { pairingStatus, scanCode, type MobileError } from "./mobileSession";
import { parseHash } from "./mobileDeviceChats";
import { OctryxMark } from "./OctryxMark";

type Step =
  | { kind: "scanning" }
  | { kind: "waiting"; number: string }
  | { kind: "confirmed"; claim: string }
  | { kind: "failed"; message: string };

const MESSAGES: Record<string, string> = {
  mobile_pairing_expired: "This code expired. Start again on your Mac.",
  mobile_pairing_used: "This code was already used. Start again on your Mac.",
  mobile_pairing_not_found: "This code is not valid. Start again on your Mac.",
  mobile_pairing_denied: "Your Mac declined the connection.",
  mobile_rate_limited:
    "Too many attempts. Wait a minute and start again on your Mac.",
};

const standalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true;

export function PairPage({ onClaim }: { onClaim: (claim: string) => void }) {
  const [step, setStep] = useState<Step>({ kind: "scanning" });

  useEffect(() => {
    const code = parseHash(window.location.hash).c || "";
    // The code leaves the address bar and the history at once.
    window.history.replaceState(null, "", "/m/pair");
    if (!code) {
      setStep({
        kind: "failed",
        message: "Scan the QR code your Mac shows (octryx-claude mobile pair).",
      });
      return;
    }
    let stopped = false;
    let timer = 0;
    const fail = (error: unknown) => {
      const code = (error as MobileError).code ?? "";
      if (!stopped)
        setStep({
          kind: "failed",
          message:
            MESSAGES[code] ??
            "The platform could not be reached. Is the VPN on?",
        });
    };
    scanCode(code).then((scan) => {
      if (stopped) return;
      setStep({ kind: "waiting", number: scan.match_number });
      const poll = () => {
        pairingStatus(scan.pairing_id, scan.scan_secret).then((status) => {
          if (stopped) return;
          if (status.state === "confirmed") {
            if (standalone()) {
              onClaim(status.claim); // pairing again from inside the app: sign in right here
              return;
            }
            // The Home Screen app starts from this address and redeems the claim on its first start.
            window.history.replaceState(
              null,
              "",
              `/m/#claim=${encodeURIComponent(status.claim)}`,
            );
            setStep({ kind: "confirmed", claim: status.claim });
          } else {
            timer = window.setTimeout(poll, 1500);
          }
        }, fail);
      };
      poll();
    }, fail);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [onClaim]);

  return (
    <main className="m-center">
      <OctryxMark size={56} />
      <h1 className="m-title">Connect your iPhone</h1>
      {step.kind === "scanning" && (
        <p className="m-muted">Checking the code…</p>
      )}
      {step.kind === "waiting" && (
        <section className="m-card m-step" aria-live="polite">
          <span className="m-eyebrow">Step 1 · Confirm on your Mac</span>
          <strong className="m-number">{step.number}</strong>
          <p className="m-muted">
            Your Mac shows the same number. Confirm it there.
          </p>
        </section>
      )}
      {step.kind === "confirmed" && (
        <>
          <section className="m-card m-step">
            <span className="m-eyebrow">Step 2 · Add to Home Screen</span>
            <p>
              Tap <b>Share</b>, then <b>Add to Home Screen</b>. Open Octryx from
              your Home Screen.
            </p>
          </section>
          <section className="m-card m-step">
            <span className="m-eyebrow">If Octryx asks for a code</span>
            <strong className="m-code">{step.claim}</strong>
            <p className="m-muted">Valid for 15 minutes, once.</p>
          </section>
        </>
      )}
      {step.kind === "failed" && (
        <p className="m-error" role="alert">
          {step.message}
        </p>
      )}
    </main>
  );
}
