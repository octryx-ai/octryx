import { useEffect, useState } from "react";

import { listSsoProviders, loadMyClaims, saveSsoMapping } from "./workRolesApi";
import { errorView, type ErrorView } from "./workRolesModel";
import { Card, ErrorLine } from "./WorkRolesParts";
import type { MyClaims, SsoProvider } from "./workRolesTypes";

// SSO mapping (board 8, contract §3.4): per identity provider, which claim carries the groups and which the roles,
// "Test with my sign-in", and how many values sign-ins have brought so far.
export function SsoMappingCards({ canEdit }: { canEdit: boolean }) {
  const [providers, setProviders] = useState<SsoProvider[] | null>(null);
  const [error, setError] = useState<ErrorView | null>(null);
  useEffect(() => {
    listSsoProviders().then(setProviders).catch((failure) => {
      setProviders([]);
      setError(errorView(failure, "The SSO mapping could not be loaded."));
    });
  }, []);
  if (providers === null) return <Card title="SSO mapping"><p className="wr-hint" role="status">Loading the identity providers…</p></Card>;
  if (!providers.length) {
    return (
      <Card title="SSO mapping" testId="sso-mapping">
        <ErrorLine error={error} />
        {error ? null : <p className="ds-empty">No identity provider is set up. Add one under Sign-in to assign SSO groups and roles.</p>}
      </Card>
    );
  }
  return <>{providers.map((provider) => <SsoProviderCard key={provider.id} provider={provider} canEdit={canEdit} />)}</>;
}

// The claim names being edited, the saved mapping, the claims of the admin's last sign-in, and save and test.
function useSsoProvider(initial: SsoProvider) {
  const [provider, setProvider] = useState(initial);
  const [groupsClaim, setGroupsClaim] = useState(initial.groups_claim);
  const [rolesClaim, setRolesClaim] = useState(initial.roles_claim);
  const [claims, setClaims] = useState<MyClaims | null>(null);
  const [error, setError] = useState<ErrorView | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const changed = groupsClaim.trim() !== provider.groups_claim || rolesClaim.trim() !== provider.roles_claim;

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const next = await saveSsoMapping(provider.id, groupsClaim.trim(), rolesClaim.trim());
      setProvider(next);
      setGroupsClaim(next.groups_claim);
      setRolesClaim(next.roles_claim);
      setSaved(true);
    } catch (failure) {
      setError(errorView(failure));
    } finally {
      setBusy(false);
    }
  };
  const test = async () => {
    setBusy(true);
    setError(null);
    try {
      setClaims(await loadMyClaims(provider.id));
    } catch (failure) {
      setError(errorView(failure, "Your last sign-in could not be read."));
    } finally {
      setBusy(false);
    }
  };

  return { provider, groupsClaim, setGroupsClaim, rolesClaim, setRolesClaim, claims, error, busy, saved, changed, save, test };
}

function SsoProviderCard({ provider: initial, canEdit }: { provider: SsoProvider; canEdit: boolean }) {
  const { provider, groupsClaim, setGroupsClaim, rolesClaim, setRolesClaim, claims, error, busy, saved, changed, save, test } =
    useSsoProvider(initial);

  const claimLine = (values: string[] | undefined) =>
    !claims ? null : values && values.length
      ? <p className="wr-sso__claims">Your last sign-in: {values.map((value, i) => <span key={value}>{i ? ", " : ""}<code>{value}</code></span>)}</p>
      : <p className="wr-sso__claims">Your last sign-in carried no value here.</p>;

  return (
    <Card title={`SSO mapping · ${provider.name}`} testId={`sso-mapping-${provider.id}`}
      meta={<>Set once per identity provider. Nested names such as <span className="wr-code">realm_access.roles</span> work. Changes apply at each person's next sign-in.</>}
      actions={(
        <>
          <button type="button" className="ds-btn" disabled={busy} data-testid="sso-test" onClick={() => void test()}>Test with my sign-in</button>
          {canEdit ? (
            <button type="button" className="ds-btn" disabled={busy || !changed || !groupsClaim.trim() || !rolesClaim.trim()}
              data-testid="sso-save" onClick={() => void save()}>Save claims</button>
          ) : null}
        </>
      )}>
      <ErrorLine error={error} />
      <div className="wr-sso">
        <div className="wr-sso__col">
          <label className="wr-field">
            <span>Claim with the SSO groups</span>
            <input className="wr-mono" value={groupsClaim} disabled={!canEdit} onChange={(event) => setGroupsClaim(event.target.value)} />
          </label>
          {claimLine(claims?.groups)}
        </div>
        <div className="wr-sso__col">
          <label className="wr-field">
            <span>Claim with the SSO roles</span>
            <input className="wr-mono" value={rolesClaim} disabled={!canEdit} onChange={(event) => setRolesClaim(event.target.value)} />
          </label>
          {claimLine(claims?.roles)}
        </div>
        <div className="wr-sso__col">
          <span className="wr-sso__label">Known from sign-ins</span>
          <span className="wr-sso__value" data-testid="sso-known">
            {provider.known_groups.length} SSO {provider.known_groups.length === 1 ? "group" : "groups"} · {provider.known_roles.length} SSO {provider.known_roles.length === 1 ? "role" : "roles"}
          </span>
          <span className="wr-sso__claims">Offered when you assign roles in a Workspace; a name nobody has signed in with yet can be typed.</span>
        </div>
      </div>
      {saved ? <p className="wr-hint" role="status">Saved. Each person's groups and roles are read again at their next sign-in.</p> : null}
    </Card>
  );
}
