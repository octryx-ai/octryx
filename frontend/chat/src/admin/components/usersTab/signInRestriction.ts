type ReadJson = <T>(url: string, init?: RequestInit) => Promise<T>;

export type SignInSaveOutcome =
  | { state: "saved"; effective: boolean }
  // The write may or may not have been applied; `effective` is what the server reports now.
  | { state: "unconfirmed"; effective: boolean }
  // Neither the write nor the current value could be confirmed.
  | { state: "unknown" };

const RUNTIME_SETTINGS = "/admin/chat/api/panel/runtime-settings";

// Saves only `auth_oidc_only` (the runtime-settings PUT accepts partial
// bodies). A failed response is never treated as "nothing changed": the
// effective value is read back, because the server may have committed the write
// before the response failed.
export async function saveSignInRestriction(readJson: ReadJson, oidcOnly: boolean): Promise<SignInSaveOutcome> {
  try {
    const updated = await readJson<{ auth_oidc_only?: boolean }>(RUNTIME_SETTINGS, {
      method: "PUT",
      body: JSON.stringify({ auth_oidc_only: oidcOnly }),
    });
    return { state: "saved", effective: Boolean(updated?.auth_oidc_only) };
  } catch {
    try {
      const current = await readJson<{ auth_oidc_only?: boolean }>(RUNTIME_SETTINGS);
      return { state: "unconfirmed", effective: Boolean(current?.auth_oidc_only) };
    } catch {
      return { state: "unknown" };
    }
  }
}

// What the page may claim about the effective setting after a save attempt:
// after an unknown outcome the stored value is only the last confirmed one.
export function signInEffectiveLabel(
  saveState: "idle" | "saving" | "saved" | "unconfirmed" | "unknown",
  lastConfirmedOidcOnly: boolean,
): { known: boolean; text: string } {
  const describe = (oidcOnly: boolean) => (oidcOnly ? "SSO only — password login is refused" : "Password and SSO sign-in allowed");
  if (saveState === "unknown") {
    return { known: false, text: `Unknown — last confirmed: ${describe(lastConfirmedOidcOnly)}` };
  }
  return { known: true, text: describe(lastConfirmedOidcOnly) };
}
