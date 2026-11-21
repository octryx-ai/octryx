import { useState } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { saveSource } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { SourceRow } from "./skillDeliveryTypes";
import { TRUST_CHOICES } from "./skillTabsModel";

// Edit an upstream source's label and trust (WP 2.9). The trust label is shown on every entry imported from
// the source; the URL, ref and path stay as imported.
export function SkillSourceDrawer({ source, onClose, onSaved }: {
  source: SourceRow;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [label, setLabel] = useState(source.label);
  const [trust, setTrust] = useState(TRUST_CHOICES.some((choice) => choice.value === source.trust) ? source.trust : "community");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await saveSource(source.id, { label: label.trim(), trust });
      await onSaved();
    } catch (error) {
      setProblem(refusalText(error));
      setBusy(false);
    }
  };

  const footer = (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="source-save"
        disabled={busy || !label.trim()} onClick={() => void save()}>Save</button>
    </>
  );

  return (
    <SettingsDrawer eyebrow="Skills · Sources" title="Edit source" size="edit" onClose={onClose} footer={footer}>
      <div className="admin-panel__stack" data-testid="source-drawer">
        <label className="admin-panel__field"><span>Label</span>
          <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Name shown on imported entries" data-testid="source-label" /></label>
        <label className="admin-panel__field"><span>Trust</span>
          <select value={trust} onChange={(event) => setTrust(event.target.value)} data-testid="source-trust">
            {TRUST_CHOICES.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
          </select></label>
        <p className="skills__hint">Mark a source <b>Official</b> only when it is the publisher&apos;s own repository or the official
          marketplace. <b>Internal</b> is for your organization&apos;s own repositories.</p>
        {source.url ? <p className="skills__hint">URL <span className="admin-policy-inline-code">{source.url}</span></p> : null}
        {problem ? <p className="workspace-classification__message" role="alert" data-testid="source-problem">{problem}</p> : null}
      </div>
    </SettingsDrawer>
  );
}
