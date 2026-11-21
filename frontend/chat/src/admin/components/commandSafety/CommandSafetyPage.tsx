import { useCallback, useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { OptionCards, ToggleRow } from "../settingsKit/SettingsKit";
import "../settingsKit/settingsKit.css";
import { CommandSafetyGateForm } from "./CommandSafetyGateForm";
import type { CommandSafety, GateSettings, GuardRule, WorkspaceRow } from "./commandSafetyModel";
import { gatePayload, gateProblems, readCommandSafety, readGate, saveErrorText } from "./commandSafetyModel";

const PATH = "/api/v1/admin/command-safety";

// Settings → Security → "Command safety": every shell, kubectl and script command an agent wants
// to run is checked; the strictest check wins. One page, one save; each Workspace inherits or overrides with the same
// form.
export function CommandSafetyPage() {
  const [saved, setSaved] = useState<CommandSafety | null>(null);
  const [draft, setDraft] = useState<CommandSafety | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<WorkspaceRow | null>(null);

  const apply = (answer: unknown) => {
    const read = readCommandSafety(answer);
    setSaved(read);
    setDraft(read);
  };
  const load = useCallback(async () => {
    try {
      apply(await readJson<unknown>(PATH));
    } catch (error) {
      setProblem((error as { status?: number }).status === 403 ? "Only platform admins can see command safety." : "Command safety could not be loaded.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (problem) return <p className="sk-err" role="alert">{problem}</p>;
  if (!draft || !saved) return <p className="sk-hint" role="status">Loading command safety…</p>;

  const problems = gateProblems(draft);
  const changed = JSON.stringify(draft) !== JSON.stringify(saved);
  const setRules = (key: "guardRules" | "customGuardRules", rule: GuardRule, enabled: boolean) =>
    setDraft({ ...draft, [key]: draft[key].map((item) => (item.id === rule.id ? { ...item, enabled } : item)) });
  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      apply(await readJson<unknown>(PATH, { method: "PUT", body: JSON.stringify(gatePayload(draft, draft.guardRules, draft.customGuardRules)) }));
      setMessage({ ok: true, text: "Command safety saved." });
    } catch (error) {
      setMessage({ ok: false, text: saveErrorText(error) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sk-page" data-testid="command-safety">
      <CommandSafetyGateForm value={draft} onChange={(next) => setDraft({ ...draft, ...next })} disabled={busy} />
      {draft.guardRules.length || draft.customGuardRules.length ? (
        <section className="admin-panel__card" aria-label="Agent guard rules">
          <div className="admin-panel__section-header"><span>Agent guard rules</span><span className="sk-muted">checked before each tool call</span></div>
          {[...draft.guardRules.map((rule) => ["guardRules", rule] as const), ...draft.customGuardRules.map((rule) => ["customGuardRules", rule] as const)]
            .map(([key, rule]) => (
              <ToggleRow key={`${key}:${rule.id}`} title={rule.label} sub={rule.description || undefined} on={rule.enabled}
                disabled={busy || rule.locked} testId={`command-guard-${rule.id}`} onChange={(enabled) => setRules(key, rule, enabled)} />
            ))}
        </section>
      ) : null}
      <section className="admin-panel__card" aria-label="Workspace overrides">
        <div className="admin-panel__section-header"><span>Workspace overrides</span></div>
        <table className="admin-panel__table sk-cards" data-testid="command-workspaces">
          <thead><tr><th>Workspace</th><th>Setting</th><th>Difference</th><th /></tr></thead>
          <tbody>
            {saved.workspaces.length === 0 ? <tr><td colSpan={4} className="admin-panel__cell--muted">No active Workspace.</td></tr> : null}
            {saved.workspaces.map((workspace) => (
              <tr key={workspace.id}>
                <td data-label="Workspace">{workspace.name}</td>
                <td data-label="Setting">
                  <span className={`work-badge ${workspace.mode === "override" ? "work-badge--attention" : "work-badge--neutral"}`}>
                    {workspace.mode === "override" ? "Override" : "Inherit"}
                  </span>
                </td>
                <td data-label="Difference" className={workspace.differences.length ? "" : "admin-panel__cell--muted"}>
                  {workspace.differences.join(" · ") || "–"}
                </td>
                <td>
                  <button type="button" className="admin-panel__action-btn" data-testid={`command-workspace-${workspace.id}`}
                    onClick={() => setEditing(workspace)}>Edit</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {problems.length ? <ul className="sk-err" role="alert">{problems.map((line) => <li key={line}>{line}</li>)}</ul> : null}
      {message ? <p className={message.ok ? "admin-panel__success" : "sk-err"} role={message.ok ? "status" : "alert"}>{message.text}</p> : null}
      <div className="sk-row sk-row--end">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="command-save"
          disabled={busy || !changed || problems.length > 0} onClick={() => void save()}>
          {busy ? "Saving…" : "Save command safety"}
        </button>
      </div>
      {editing ? (
        <CommandSafetyWorkspaceDrawer workspace={editing} platform={saved} onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); void load(); }} />
      ) : null}
    </div>
  );
}

// A Workspace's gate: inherit the platform, or override with the same form (only differences are stored).
export function CommandSafetyWorkspaceDrawer({ workspace, platform, onClose, onSaved }: {
  workspace: { id: string; name: string };
  platform: GateSettings;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [mode, setMode] = useState<"inherit" | "override" | null>(null);
  const [settings, setSettings] = useState<GateSettings | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const path = `${PATH}/workspaces/${encodeURIComponent(workspace.id)}`;

  useEffect(() => {
    let cancelled = false;
    readJson<{ mode?: string; settings?: unknown }>(path)
      .then((answer) => {
        if (cancelled) return;
        setMode(answer.mode === "override" ? "override" : "inherit");
        setSettings(readGate(answer.settings) ?? platform);
      })
      .catch(() => { if (!cancelled) setProblem("The Workspace's command safety could not be loaded."); });
    return () => { cancelled = true; };
  }, [path, platform]);

  const problems = mode === "override" && settings ? gateProblems(settings) : [];
  const save = async () => {
    setBusy(true);
    try {
      await readJson<unknown>(path, {
        method: "PUT",
        body: JSON.stringify(mode === "override" && settings ? { mode, settings: gatePayload(settings) } : { mode: "inherit" }),
      });
      onSaved();
    } catch (error) {
      setProblem(saveErrorText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingsDrawer eyebrow="Command safety · Workspace" title={workspace.name} size="detail" onClose={onClose}
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="command-workspace-save"
            disabled={busy || !mode || problems.length > 0} onClick={() => void save()}>Save</button>
        </>
      )}>
      <div className="sk-page">
        {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
        {mode ? (
          <OptionCards name={`command-mode-${workspace.id}`} label="Command safety for this Workspace" value={mode}
            onChange={(next) => { setMode(next); if (next === "override" && !settings) setSettings(platform); }}
            options={[
              { value: "inherit", title: "Inherit platform", desc: "The platform's checks, scores and lists apply." },
              { value: "override", title: "Override", desc: "This Workspace uses its own values; only the differences are stored." },
            ]} />
        ) : <p className="sk-hint" role="status">Loading…</p>}
        {mode === "override" && settings ? <CommandSafetyGateForm value={settings} onChange={setSettings} disabled={busy} /> : null}
        {problems.length ? <ul className="sk-err" role="alert">{problems.map((line) => <li key={line}>{line}</li>)}</ul> : null}
      </div>
    </SettingsDrawer>
  );
}
