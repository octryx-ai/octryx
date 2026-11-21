import { useEffect, useState } from "react";

import { LOCK_GROUPS, toggleLock } from "./corpStudioLocksModel";

// Corporate identity › profile › "Spec Studio locks": the values of
// this profile a spec may not change. Unlocked values may differ with a reason the product owner gives in the Studio.

export function CorpStudioLocks({ profileId, locks: initial }: { profileId: string; locks: string[] }) {
  const [locks, setLocks] = useState(initial);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setLocks(initial), [initial]);

  const save = async (next: string[]) => {
    setBusy(true);
    setProblem(null);
    try {
      const response = await fetch(`/admin/chat/api/panel/corp-identities/${encodeURIComponent(profileId)}/studio-locks`, {
        method: "PUT", credentials: "same-origin",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ paths: next }),
      });
      if (!response.ok) throw new Error(String(response.status));
      setLocks(((await response.json()) as { studio_locks: string[] }).studio_locks);
    } catch {
      setProblem("The locks could not be saved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="user-edit-panel__section" data-testid="corp-studio-locks">
      <p className="user-edit-panel__section-label">Spec Studio locks</p>
      <p className="admin-panel__hint">Locked values are read-only in the Spec Studio. Everything else may differ, with a reason that goes into the spec.</p>
      {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
      {LOCK_GROUPS.map((group) => (
        <fieldset key={group.title} className="corp-locks">
          <legend className="corp-muted">{group.title}</legend>
          {group.paths.map(({ path, label }) => (
            <label key={path} className="admin-panel__checkbox corp-locks__item">
              <input type="checkbox" checked={locks.includes(path)} disabled={busy}
                onChange={(event) => void save(toggleLock(locks, path, event.target.checked))} />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
      ))}
    </section>
  );
}
