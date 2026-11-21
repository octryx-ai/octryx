import { useCallback, useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import type { Budget } from "./workspaceSettingsModel";
import { budgetAmount, platformBudgetText, readBudget, settingsErrorText } from "./workspaceSettingsModel";

type Field = keyof Budget;
const FIELDS: { key: Field; label: string }[] = [
  { key: "session_usd", label: "USD per session" },
  { key: "request_usd", label: "USD per request" },
  { key: "per_person_daily_usd", label: "USD per person per day" },
];

const asText = (budget: Budget): Record<Field, string> => ({
  session_usd: budget.session_usd === null ? "" : String(budget.session_usd),
  request_usd: budget.request_usd === null ? "" : String(budget.request_usd),
  per_person_daily_usd: budget.per_person_daily_usd === null ? "" : String(budget.per_person_daily_usd),
});

// Workspace → Rules → Budget: overrides of the platform caps. An empty field is the platform value (inherit).
export function WorkspaceBudgetInputs({ projectId }: { projectId: string }) {
  const path = `/api/v1/admin/workspaces/${encodeURIComponent(projectId)}/budget`;
  const [saved, setSaved] = useState<Record<Field, string> | null>(null);
  const [draft, setDraft] = useState<Record<Field, string> | null>(null);
  const [platform, setPlatform] = useState<Budget | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const apply = (answer: unknown) => {
    const read = readBudget(answer);
    if (!read) return;
    setSaved(asText(read));
    setDraft(asText(read));
    setPlatform(read.platform);
  };
  const load = useCallback(async () => {
    try {
      apply(await readJson<unknown>(path));
    } catch {
      setMessage({ ok: false, text: "The budget could not be loaded." });
    }
  }, [path]);
  useEffect(() => { void load(); }, [load]);

  if (!draft || !saved) return message ? <p className="sk-err" role="alert">{message.text}</p> : <span className="sk-muted">Loading…</span>;
  const amounts = Object.fromEntries(FIELDS.map(({ key }) => [key, budgetAmount(draft[key])])) as Record<Field, number | null | "invalid">;
  const invalid = Object.values(amounts).includes("invalid");
  const changed = JSON.stringify(draft) !== JSON.stringify(saved);
  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      apply(await readJson<unknown>(path, { method: "PUT", body: JSON.stringify(amounts) }));
      setMessage({ ok: true, text: "Budget saved." });
    } catch (error) {
      setMessage({ ok: false, text: settingsErrorText(error) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="sk-page" data-testid="workspace-budget">
      <div className="sk-row">
        {FIELDS.map(({ key, label }) => (
          <input key={key} className="admin-users__toolbar-input sk-num" inputMode="decimal" value={draft[key]} aria-label={label} title={label}
            data-testid={`budget-${key}`} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
        ))}
        <button type="button" className="admin-panel__action-btn" data-testid="budget-save" disabled={busy || invalid || !changed}
          onClick={() => void save()}>Save</button>
      </div>
      <div className="sk-sub">per session · per request · per person/day — empty = platform value</div>
      {platform ? <div className="sk-sub" data-testid="budget-platform">{platformBudgetText(platform)}</div> : null}
      {invalid ? <p className="sk-err" role="alert">Enter an amount of 0 or more, or leave the field empty.</p> : null}
      {message ? <p className={message.ok ? "admin-panel__success" : "sk-err"} role={message.ok ? "status" : "alert"}>{message.text}</p> : null}
    </div>
  );
}
