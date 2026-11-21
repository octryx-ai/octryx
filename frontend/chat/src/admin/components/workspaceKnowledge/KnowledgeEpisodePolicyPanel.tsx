import { useCallback, useEffect, useState } from "react";
import { describeUnknownValue, episodePolicyApi, episodePolicyPayload, episodePolicyView } from "./episodePolicy";
import type { EpisodeSettings } from "./episodePolicy";

// Whether sessions of this workspace may return what they learned as cited episodes. A switch takes effect at
// once; only a workspace admin or owner may change it, and keys this UI does not know stay as the server has them.
export function KnowledgeEpisodePolicyPanel({ workspaceId }: { workspaceId: string }) {
  const [settings, setSettings] = useState<EpisodeSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const run = useCallback(async (action: () => Promise<EpisodeSettings>) => {
    setBusy(true);
    try {
      setSettings(await action());
      setMessage(null);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void run(() => episodePolicyApi.get(workspaceId));
  }, [run, workspaceId]);

  if (!settings) return <div className="admin-panel__hint">{message ?? "Loading…"}</div>;
  const view = episodePolicyView(settings);
  const toggle = (key: string, value: boolean) =>
    void run(() => episodePolicyApi.put(workspaceId, episodePolicyPayload(settings, key, value)));

  return (
    <div className="admin-panel__stack">
      <EpisodeSwitches view={view} busy={busy} toggle={toggle} />

      {message ? <div className="admin-panel__hint" role="status">{message}</div> : null}

      <UnknownPolicyKeys view={view} />
    </div>
  );
}

// The known switches, each taking effect at once, with who may change them and whether episodes can link back.
function EpisodeSwitches({ view, busy, toggle }: {
  view: ReturnType<typeof episodePolicyView>;
  busy: boolean;
  toggle: (key: string, value: boolean) => void;
}) {
  return (
    <div className="user-edit-panel__section">
      <div className="user-edit-panel__section-label">Session episodes</div>
      <div className="admin-panel__stack admin-panel__stack--compact">
        {view.switches.map((row) => (
          <div key={row.key} className="admin-form-toggle-row" data-policy-key={row.key}>
            <div className="admin-form-toggle-copy">
              <span>{row.label}</span>
              <div className="admin-form-help">{row.explanation}</div>
            </div>
            <button
              type="button"
              className={`toggle-switch ${row.value ? "toggle-switch--on" : ""}`}
              role="switch"
              aria-checked={row.value}
              aria-label={row.label}
              disabled={busy || !view.mayAuthor}
              onClick={() => toggle(row.key, !row.value)}
            />
          </div>
        ))}
        {view.switches.length === 0 ? (
          <div className="admin-panel__hint" style={{ margin: 0 }}>The server returned no episode switches.</div>
        ) : null}
        {!view.mayAuthor ? (
          <div className="admin-panel__hint" style={{ margin: 0 }}>
            Only a workspace admin or owner can change these switches.
          </div>
        ) : null}
        {!view.publicOriginConfigured ? (
          <div className="admin-panel__hint" style={{ margin: 0 }}>
            Episodes are refused until a platform operator sets the platform's public address, because they cannot
            link back to their session without it.
          </div>
        ) : null}
      </div>
    </div>
  );
}

// Keys this UI does not know, shown read-only and kept as the server has them.
function UnknownPolicyKeys({ view }: { view: ReturnType<typeof episodePolicyView> }) {
  return view.unknown.length ? (
    <div className="user-edit-panel__section">
      <div className="user-edit-panel__section-label">Other policy keys (read-only)</div>
      <div className="admin-panel__table-wrap">
        <table className="admin-panel__table" style={{ border: "none", borderRadius: 0 }}>
          <thead>
            <tr><th>Key</th><th>Value</th></tr>
          </thead>
          <tbody>
            {view.unknown.map((row) => (
              <tr key={row.key} data-policy-key={row.key}>
                <td><code>{row.key}</code></td>
                <td><code>{describeUnknownValue(row.value)}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="admin-panel__hint" style={{ margin: 0 }}>
        Saving a switch keeps these values unchanged.
      </div>
    </div>
  ) : null;
}
