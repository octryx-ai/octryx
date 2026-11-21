import { useEffect, useState } from "react";
import {
  browserNotificationState,
  browserNotificationText,
  readNotifyToggle,
  requestBrowserNotifications,
  storeNotifyToggle,
  type BrowserNotificationState,
  type NotificationApi,
} from "../agents/browserNotifications";
import { loadQuietHours, saveQuietHours } from "./companionApi";
import { quietSaveErrorText } from "./companionHandoverModel";
import { DEFAULT_QUIET_HOURS, type QuietHours } from "./companionTypes";
import { validQuietHours } from "./companionModel";

// The panel's settings (behind the gear): quiet hours (notification preferences, default 19:00–08:00 Europe/Zurich) and the browser
// notification switch. Permission is asked only on a click.

export type CompanionFooterProps = { userId: string; notificationApi: NotificationApi | null };

type Loaded = { quiet: QuietHours; stored: boolean; preferences: unknown };

export function CompanionFooter({ userId, notificationApi }: CompanionFooterProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [draft, setDraft] = useState<QuietHours>({ ...DEFAULT_QUIET_HOURS });
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [permission, setPermission] = useState<BrowserNotificationState>(() => browserNotificationState(notificationApi));
  const [notifyOn, setNotifyOn] = useState(() => readNotifyToggle(userId));

  useEffect(() => {
    let current = true;
    loadQuietHours().then((next) => {
      if (!current) return;
      setLoaded(next);
      setDraft(next.quiet);
    }).catch(() => {
      if (current) setStatus("Quiet hours could not be loaded; the default applies.");
    });
    return () => { current = false; };
  }, []);

  const save = () => {
    if (!validQuietHours(draft)) { setStatus("Choose a start and an end time that differ."); return; }
    setSaving(true);
    setStatus(null);
    saveQuietHours(loaded?.preferences ?? null, draft).then((next) => {
      setLoaded(next);
      setDraft(next.quiet);
      setStatus(next.stored ? "Quiet hours saved." : "This server does not keep quiet hours yet; nothing was changed.");
    }).catch((error: { code?: string | null; message?: string }) => setStatus(quietSaveErrorText(error)))
      .finally(() => setSaving(false));
  };

  const changed = !loaded || JSON.stringify(loaded.quiet) !== JSON.stringify(draft);
  return (
    <section className="octryx-panel__settings" aria-label="Notification settings" data-testid="octryx-footer">
      <fieldset className="octryx-panel__quiet" disabled={saving}>
        <legend>Quiet hours ({draft.timezone})</legend>
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={draft.enabled} data-testid="octryx-quiet-enabled"
            onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />
          {" "}No notifications from {draft.start} to {draft.end}
        </label>
        <div className="octryx-panel__quiet-times">
          <label className="admin-panel__field">
            <span>From</span>
            <input type="time" className="admin-panel__input" value={draft.start} data-testid="octryx-quiet-start"
              onChange={(event) => setDraft({ ...draft, start: event.target.value })} />
          </label>
          <label className="admin-panel__field">
            <span>To</span>
            <input type="time" className="admin-panel__input" value={draft.end} data-testid="octryx-quiet-end"
              onChange={(event) => setDraft({ ...draft, end: event.target.value })} />
          </label>
          <button type="button" className="admin-panel__action-btn" disabled={!changed} onClick={save}>
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
        {status ? <p className="octryx-panel__hint" role="status" data-testid="octryx-quiet-status">{status}</p> : null}
      </fieldset>
      <p className="octryx-panel__hint">{browserNotificationText(permission)}</p>
      {permission === "granted" && userId ? (
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={notifyOn}
            onChange={(event) => { storeNotifyToggle(userId, event.target.checked); setNotifyOn(event.target.checked); }} />
          {" "}Notify me in this browser
        </label>
      ) : null}
      {permission === "default" || permission === "failed" ? (
        <button type="button" className="admin-panel__action-btn"
          onClick={() => void requestBrowserNotifications(notificationApi).then(setPermission)}>
          Enable browser notifications
        </button>
      ) : null}
    </section>
  );
}
