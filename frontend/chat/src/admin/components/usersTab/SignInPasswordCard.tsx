import { useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { ToggleRow } from "../settingsKit/SettingsKit";
import { saveSignInRestriction, signInEffectiveLabel } from "./signInRestriction";

type SaveState = "idle" | "saving" | "saved" | "unconfirmed" | "unknown";

// Settings → Identity → Sign-in & SSO, card "Password sign-in". One switch, `agent.auth_login_mode`; the server refuses every password login path while it is on
// (web sign-in and POST /api/v1/auth/login). There is no password exemption for any account.
export function SignInPasswordCard({ activeSsoProviders }: { activeSsoProviders: number | null }) {
  const [saved, setSaved] = useState<boolean | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");

  useEffect(() => {
    let cancelled = false;
    readJson<{ auth_oidc_only?: boolean }>("/admin/chat/api/panel/runtime-settings")
      .then((settings) => { if (!cancelled) setSaved(Boolean(settings?.auth_oidc_only)); })
      .catch(() => { if (!cancelled) setLoadFailed(true); });
    return () => { cancelled = true; };
  }, []);

  const save = async (next: boolean) => {
    setConfirming(false);
    setSaveState("saving");
    const outcome = await saveSignInRestriction(readJson, next);
    if (outcome.state !== "unknown") setSaved(outcome.effective);
    setSaveState(outcome.state);
  };
  const request = (next: boolean) => {
    if (next && activeSsoProviders === 0) { setConfirming(true); return; }
    void save(next);
  };

  return (
    <section className="admin-panel__card" aria-label="Password sign-in" data-testid="sign-in-password-card">
      <div className="admin-panel__section-header"><span>Password sign-in</span></div>
      {loadFailed ? <p className="sk-err" role="alert">The sign-in setting could not be read. Reload the page.</p> : null}
      {saved === null && !loadFailed ? <p className="sk-hint" role="status">Loading…</p> : null}
      {saved !== null ? (
        <>
          <ToggleRow title="Allow sign-in only through SSO" on={saved} disabled={saveState === "saving"} testId="sso-only-toggle"
            sub={<>Applies to the web sign-in <b>and</b> the API (<span className="admin-policy-inline-code">/api/v1/auth/login</span>).
              No account keeps a password while this is on.</>}
            onChange={request} />
          <p className="sk-hint" data-testid="sso-only-effective">
            Effective now: <b>{signInEffectiveLabel(saveState, saved).text}</b>. Active SSO providers:{" "}
            <b>{activeSsoProviders === null ? "unknown" : activeSsoProviders}</b>.
          </p>
        </>
      ) : null}
      {confirming ? (
        <div className="sk-warn" role="alertdialog" aria-label="Confirm SSO only" data-testid="sso-only-confirm">
          <p className="sk-hint">No active SSO provider is configured. Turning this on blocks every password sign-in, including administrators.</p>
          <div className="sk-row">
            <button type="button" className="admin-panel__action-btn" onClick={() => setConfirming(false)}>Cancel</button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={() => void save(true)}>
              Turn on anyway
            </button>
          </div>
        </div>
      ) : null}
      {saveState === "saved" ? <p className="admin-panel__success" role="status">Saved.</p> : null}
      {saveState === "unconfirmed" ? (
        <p className="sk-err" role="alert">The save could not be confirmed. The setting read back from the server is shown above.</p>
      ) : null}
      {saveState === "unknown" ? (
        <p className="sk-err" role="alert">The save could not be confirmed and the current setting could not be read. Reload this page.</p>
      ) : null}
    </section>
  );
}
