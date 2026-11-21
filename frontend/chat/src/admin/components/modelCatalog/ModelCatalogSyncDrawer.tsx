import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { addGatewayAlias, addSelectedModels, saveCatalogModel, syncCatalog } from "./modelCatalogApi";
import { goneText, proposalKey, readSyncResult } from "./modelCatalogSync";
import { saveErrorText } from "./modelCatalogContract";
import type { SyncResult } from "./modelCatalogSync";

type Props = { onClose: () => void; onChanged: () => void };
type Run = (action: () => Promise<unknown>, done: string, after?: (current: SyncResult) => SyncResult) => Promise<void>;

type RunState = {
  setBusy: (busy: boolean) => void;
  setError: (error: string) => void;
  setMessage: (message: string) => void;
  setResult: Dispatch<SetStateAction<SyncResult | null>>;
  onChanged: () => void;
};

/** One follow-up of the sync: the action, its done message and how it changes the shown result. */
async function runSyncAction(action: () => Promise<unknown>, done: string, after: ((current: SyncResult) => SyncResult) | undefined,
  state: RunState) {
  state.setBusy(true);
  state.setError("");
  try {
    await action();
    state.setMessage(done);
    if (after) state.setResult((current) => (current ? after(current) : current));
    state.onChanged();
  } catch (failure) {
    state.setError(saveErrorText(failure));
  } finally {
    state.setBusy(false);
  }
}

// "Sync from providers": refreshes the catalog when it opens, then offers the three follow-ups of the mock.
export function ModelCatalogSyncDrawer({ onClose, onChanged }: Props) {
  const [result, setResult] = useState<SyncResult | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    syncCatalog()
      .then((payload) => {
        if (!alive) return;
        setResult(readSyncResult(payload));
        onChanged();
      })
      .catch((failure) => alive && setError(saveErrorText(failure)));
    return () => {
      alive = false;
    };
    // The sync runs once per opening of the drawer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run: Run = (action, done, after) => runSyncAction(action, done, after, { setBusy, setError, setMessage, setResult, onChanged });

  const chosen = result?.proposals.filter((item) => selected.has(proposalKey(item))) ?? [];
  const addSelected = () => run(
    () => addSelectedModels(chosen.map((item) => ({ provider_id: item.providerId, model_id: item.modelId }))),
    `${chosen.length} ${chosen.length === 1 ? "model" : "models"} added to the catalog (not enabled).`,
    (current) => ({ ...current, proposals: current.proposals.filter((item) => !selected.has(proposalKey(item))) }),
  ).then(() => setSelected(new Set()));

  return (
    <SettingsDrawer
      eyebrow="Model catalog"
      title="Sync from providers"
      size="detail"
      onClose={onClose}
      footer={<SyncFooter disabled={busy || !chosen.length} onClose={onClose} onAdd={() => void addSelected()} />}
    >
      {!result && !error ? <p className="admin-panel__loading">Asking the providers for their models…</p> : null}
      {result?.failed.length ? (
        <p className="model-catalog__warn" role="status">Could not reach: {result.failed.join(", ")}.</p>
      ) : null}
      {result ? (
        <>
          <ProposalsSection proposals={result.proposals} selected={selected} onSelected={setSelected} />
          <GoneSection gone={result.gone} busy={busy} run={run} />
          <GatewaySection unaliased={result.unaliased} busy={busy} run={run} />
        </>
      ) : null}
      {message ? <p className="admin-panel__success" role="status">{message}</p> : null}
      {error ? <p className="admin-panel__error" role="alert">{error}</p> : null}
    </SettingsDrawer>
  );
}

function ProposalsSection({ proposals, selected, onSelected }: {
  proposals: SyncResult["proposals"];
  selected: Set<string>;
  onSelected: Dispatch<SetStateAction<Set<string>>>;
}) {
  return (
    <section className="work-detail__section">
      <h3>New upstream (added, not enabled)</h3>
      {proposals.length ? proposals.map((item) => (
        <label key={proposalKey(item)} className="admin-panel__checkbox model-catalog__check">
          <input type="checkbox" checked={selected.has(proposalKey(item))}
            onChange={(event) => onSelected((current) => {
              const next = new Set(current);
              if (event.target.checked) next.add(proposalKey(item));
              else next.delete(proposalKey(item));
              return next;
            })} />
          <div><b>{item.displayName}</b><div className="model-catalog__sub">{item.meta}</div></div>
        </label>
      )) : <p className="model-catalog__sub">No new models.</p>}
    </section>
  );
}

function GoneSection({ gone, busy, run }: { gone: SyncResult["gone"]; busy: boolean; run: Run }) {
  return (
    <section className="work-detail__section">
      <h3>Gone upstream</h3>
      {gone.length ? gone.map((item) => (
        <div key={item.id} className="model-catalog__check">
          <span className="model-catalog__dot--bad" aria-hidden="true">●</span>
          <div><b>{item.displayName}</b><div className="model-catalog__sub">{goneText(item)}</div></div>
          {item.enabled ? (
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" disabled={busy}
              onClick={() => void run(() => saveCatalogModel(item.id, { enabled: false }), `${item.displayName} disabled.`,
                (current) => ({ ...current, gone: current.gone.map((entry) => (entry.id === item.id ? { ...entry, enabled: false } : entry)) }))}>
              Disable
            </button>
          ) : null}
        </div>
      )) : <p className="model-catalog__sub">Every model is still listed by its provider.</p>}
    </section>
  );
}

function GatewaySection({ unaliased, busy, run }: { unaliased: SyncResult["unaliased"]; busy: boolean; run: Run }) {
  return (
    <section className="work-detail__section">
      <h3>Gateway</h3>
      {unaliased.length ? unaliased.map((item) => (
        <div key={item.id} className="model-catalog__check">
          <span className="model-catalog__dot--no" aria-hidden="true">●</span>
          <div>
            <b>{item.displayName}</b>
            <div className="model-catalog__sub">Served by the gateway but has no alias in the catalog, so nobody can call it.</div>
          </div>
          <button type="button" className="admin-panel__action-btn" disabled={busy}
            onClick={() => void run(() => addGatewayAlias(item.id), "Alias created (not enabled). Clear it for data before enabling.",
              (current) => ({ ...current, unaliased: current.unaliased.filter((entry) => entry.id !== item.id) }))}>
            Add to catalog
          </button>
        </div>
      )) : <p className="model-catalog__sub">Every gateway model has an alias.</p>}
    </section>
  );
}

function SyncFooter({ disabled, onClose, onAdd }: { disabled: boolean; onClose: () => void; onAdd: () => void }) {
  return (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
        data-testid="sync-add-selected" disabled={disabled} onClick={onAdd}>
        Add selected
      </button>
    </>
  );
}
