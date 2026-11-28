type ReadJson = <T>(url: string, init?: RequestInit) => Promise<T>;

export type SignInSaveOutcome =
  | { state: "saved"; effective: boolean }
  | { state: "unconfirmed"; effective: boolean }
  | { state: "unknown" };

const RUNTIME_SETTINGS = "/admin/chat/api/panel/runtime-settings";

// A failed response may still have committed the write, so the effective value is read back.
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

// After an unknown outcome the stored value is only the last confirmed one.
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
