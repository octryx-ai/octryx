import { useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { OptionCards } from "../settingsKit/SettingsKit";
import {
  SEAT_TRAFFIC_HELP,
  SEAT_TRAFFIC_OPTIONS,
  SEAT_TRAFFIC_PATH,
  readSeatTrafficSetting,
  seatTrafficBody,
  seatTrafficConfirmText,
  seatTrafficLoadOutcome,
  seatTrafficSaveError,
  type SeatTrafficMode,
  type SeatTrafficSetting,
} from "./seatTrafficModel";

/** Admin › Models › Defaults › Seat traffic: where seat calls go out. A change is confirmed in the page. */
export function SeatTrafficCard() {
  const [setting, setSetting] = useState<SeatTrafficSetting | null>(null);
  const [hidden, setHidden] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [pending, setPending] = useState<SeatTrafficMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let current = true;
    readJson<unknown>(SEAT_TRAFFIC_PATH).then((payload) => {
      if (!current) return;
      const read = readSeatTrafficSetting(payload);
      if (read) setSetting(read); else setProblem("The server's answer was not a seat traffic setting.");
    }).catch((failure: { status?: number }) => {
      if (!current) return;
      if (seatTrafficLoadOutcome(failure?.status ?? null) === "hidden") setHidden(true);
      else setProblem("The seat traffic setting could not be loaded.");
    });
    return () => { current = false; };
  }, []);

  if (hidden) return null;
  if (problem) return <section className="admin-panel__card"><p className="sk-err" role="alert">{problem}</p></section>;
  if (!setting) return null;

  const save = async (next: SeatTrafficMode) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(SEAT_TRAFFIC_PATH, {
        method: "PUT",
        credentials: "same-origin",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(seatTrafficBody(next)),
      });
      let body: unknown = null;
      try { body = await response.json(); } catch { /* keep the status */ }
      const read = response.ok ? readSeatTrafficSetting(body) : null;
      if (read) setSetting(read); else setError(seatTrafficSaveError(response.status, body));
    } catch {
      setError(seatTrafficSaveError(0, null));
    }
    setPending(null);
    setBusy(false);
  };

  return (
    <section className="admin-panel__card" aria-label="Seat traffic" data-testid="seat-traffic">
      <div className="admin-panel__section-header"><span>Seat traffic</span></div>
      <p className="sk-muted">{SEAT_TRAFFIC_HELP}</p>
      <OptionCards name="seat-traffic" label="Seat traffic" value={pending ?? setting.mode} options={SEAT_TRAFFIC_OPTIONS}
        disabled={!setting.canEdit || busy}
        onChange={(next) => { setError(null); setPending(next === setting.mode ? null : next); }} />
      {pending ? (
        <div className="sk-warn" role="alertdialog" aria-label="Confirm seat traffic" data-testid="seat-traffic-confirm">
          <p className="sk-hint">{seatTrafficConfirmText(pending)}</p>
          <div className="sk-row">
            <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setPending(null)}>Cancel</button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
              data-testid="seat-traffic-confirm-save" onClick={() => void save(pending)}>Switch</button>
          </div>
        </div>
      ) : null}
      {setting.canEdit ? <p className="sk-muted">Changes are audited.</p>
        : <p className="sk-muted">Read-only: only platform admins can change it.</p>}
      {error ? <p className="sk-err" role="alert" data-testid="seat-traffic-error">{error}</p> : null}
    </section>
  );
}
