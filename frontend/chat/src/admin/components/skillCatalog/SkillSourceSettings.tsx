import { useState } from "react";

import { saveSettings } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { CatalogSettings } from "./skillDeliveryTypes";
import { csv, intervalOptions } from "./skillTabsModel";

// The "Scheduled check" card of Sources & updates (WP 2.9): how often sources are checked, which hosts may
// be read, and the licence allow-list (SPDX). The instance always allows its fixed licences on top of the list.
export function SkillSourceSettings({ settings, onSaved }: {
  settings: CatalogSettings;
  onSaved: (next: CatalogSettings) => void;
}) {
  const [hours, setHours] = useState(settings.update_check_hours);
  const [hosts, setHosts] = useState(settings.allowed_hosts.join(", "));
  const [licences, setLicences] = useState(settings.licence_allowlist.join(", "));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; problem: boolean } | null>(null);

  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const next = (await saveSettings({ update_check_hours: hours, allowed_hosts: csv(hosts), licence_allowlist: csv(licences) })) as CatalogSettings;
      setHosts(next.allowed_hosts.join(", "));
      setLicences(next.licence_allowlist.join(", "));
      setHours(next.update_check_hours);
      setMessage({ text: "Saved.", problem: false });
      onSaved(next);
    } catch (error) {
      setMessage({ text: refusalText(error), problem: true });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="admin-panel__card" style={{ marginTop: ".9rem" }} data-testid="source-settings">
      <div className="admin-panel__section-header">Scheduled check</div>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field"><span>Check sources</span>
          <select value={hours} onChange={(event) => setHours(Number(event.target.value))} data-testid="settings-interval">
            {intervalOptions(settings.update_check_hours).map((option) => <option key={option.hours} value={option.hours}>{option.label}</option>)}
          </select></label>
        <label className="admin-panel__field"><span>Allowed hosts</span>
          <input value={hosts} onChange={(event) => setHosts(event.target.value)} placeholder="Host names, comma-separated" data-testid="settings-hosts" /></label>
        <label className="admin-panel__field"><span>Licence allow-list (SPDX)</span>
          <input value={licences} onChange={(event) => setLicences(event.target.value)} placeholder="SPDX identifiers, comma-separated" data-testid="settings-licences" /></label>
      </div>
      {settings.always_allowed_licences.length ? (
        <p className="skills__hint">Always allowed: {settings.always_allowed_licences.map((name) => (
          <span key={name} className="work-badge work-badge--neutral" style={{ marginRight: ".25rem" }}>{name}</span>
        ))}</p>
      ) : null}
      <p className="skills__hint">The check fetches only refs and the skill paths (read-only, size-limited, no submodules, no Git LFS).
        Hosts outside the list are refused (<span className="admin-policy-inline-code">skill_source_host_not_allowed</span>).</p>
      <div className="policies__row">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy} data-testid="settings-save"
          onClick={() => void save()}>Save</button>
        {message ? (
          <span className={message.problem ? "workspace-classification__message" : "admin-panel__hint"} role={message.problem ? "alert" : "status"}
            data-testid="settings-message">{message.text}</span>
        ) : null}
      </div>
    </div>
  );
}
