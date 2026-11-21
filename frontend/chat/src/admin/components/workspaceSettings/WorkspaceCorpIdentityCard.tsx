import { useEffect, useId, useState } from "react";

import { readJson } from "../../../chat/chatApiClient";
import { companyDefaultLabel, lockLabel, type Profile } from "../corpIdentity/corpStudioLocksModel";

// Workspace settings › Rules › "Corporate identity": which of the
// platform's Corporate Identity profiles this Workspace's products look like in the Spec Studio. Empty is the
// company default. Changing it reaches open specs and new ones, never an approved version. Admins choose; everyone
// else reads.

type View = { chosen: string; effective: { profile_id: string; profile_name: string; source: string; locks: string[] } };

const address = (projectId: string) => `/admin/chat/api/panel/workspaces/${encodeURIComponent(projectId)}/corp-identity`;

export function WorkspaceCorpIdentityCard({ projectId, isAdmin }: { projectId: string; isAdmin: boolean }) {
  const [view, setView] = useState<View | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const id = useId();

  useEffect(() => {
    if (!isAdmin) return undefined;
    let current = true;
    setView(null);
    setProblem(null);
    Promise.all([readJson<View>(address(projectId)),
      readJson<{ profiles: Profile[] }>("/admin/chat/api/panel/corp-identities")])
      .then(([loaded, list]) => { if (current) { setView(loaded); setProfiles(list.profiles ?? []); } })
      .catch(() => { if (current) setProblem("The corporate identity could not be loaded."); });
    return () => { current = false; };
  }, [projectId, isAdmin]);

  const choose = async (profileId: string) => {
    setBusy(true);
    setProblem(null);
    try {
      const response = await fetch(address(projectId), {
        method: "PUT", credentials: "same-origin",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ profile_id: profileId }),
      });
      if (!response.ok) throw new Error(String(response.status));
      setView(await response.json() as View);
    } catch {
      setProblem("The corporate identity could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="admin-panel__card" aria-label="Corporate identity" data-testid="workspace-corp-identity">
      <div className="admin-panel__section-header"><span>Corporate identity</span></div>
      {/* Spans, not paragraphs: the card's grid gap spaces them; a <p>'s default margin doubled it. */}
      <span className="sk-muted">The look of the products specified in the Spec Studio. Affects open specs and new ones, never approved versions.</span>
      {!isAdmin ? <span className="sk-muted">An admin chooses it on the Corporate identity page.</span> : null}
      {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
      {isAdmin && view ? (
        <label className="admin-panel__field" htmlFor={id}>
          <span>Profile</span>
          <select id={id} className="admin-users__toolbar-select ds-input" value={view.chosen} disabled={busy}
            onChange={(event) => void choose(event.target.value)}>
            <option value="">{companyDefaultLabel(profiles)}</option>
            {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
          </select>
          {view.effective.locks.length ? (
            <span className="sk-muted">Locked in the Spec Studio: {view.effective.locks.map(lockLabel).join(", ")}</span>
          ) : <span className="sk-muted">No values locked: a spec may deviate with a reason.</span>}
        </label>
      ) : null}
    </section>
  );
}
