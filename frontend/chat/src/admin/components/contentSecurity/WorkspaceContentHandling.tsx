import { useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import {
  ACTION_EXPLANATIONS, DEFAULT_CHOICE, NO_ALIASES_TEXT, READ_ONLY_TEXT, actionText, aliasBody, aliasProblem, aliasText,
  choiceBody, choicePreviewLines, choiceProblem, choiceUnchanged, contentHandlingLoadErrorText,
  contentHandlingSaveErrorText, defaultOptionText, effectiveText, initialChoice, readContentHandling, readHandlingKind,
  surfaceDefaultLines,
} from "./workspaceContentHandlingModel";
import type { ContentHandling, HandlingChoice, HandlingKind } from "./workspaceContentHandlingModel";

const path = (workspaceId: string) => `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/content-handling`;
type Message = { ok: boolean; text: string } | null;

function SaveMessage({ message, testId }: { message: Message; testId: string }) {
  if (!message) return null;
  return (
    <p className={message.ok ? "admin-panel__success" : "work-area__error"} role={message.ok ? "status" : "alert"}
      data-testid={testId}>{message.text}</p>
  );
}

// The Workspace's one governance alias: where every reroute / mask_reroute kind is sent.
function GovernanceAlias({ workspaceId, data, onSaved }: {
  workspaceId: string; data: ContentHandling; onSaved: (alias: string | null) => void;
}) {
  const [alias, setAlias] = useState<string | null>(data.governanceAlias);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const problem = alias === data.governanceAlias ? null : aliasProblem(alias, data);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const saved = await readJson<{ governance_alias?: unknown }>(`${path(workspaceId)}/governance-alias`, {
        method: "PUT", body: JSON.stringify(aliasBody(alias)),
      });
      const stored = typeof saved?.governance_alias === "string" ? saved.governance_alias : null;
      onSaved(stored);
      setAlias(stored);
      setMessage({ ok: true, text: "Saved." });
    } catch (error) {
      setMessage({ ok: false, text: contentHandlingSaveErrorText(error) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-testid="content-handling-governance">
      <span className="workspace-classification__heading">Governance alias</span>
      <p className="admin-panel__hint">Reroute and Mask and reroute send the content to this one governed alias.</p>
      <p data-testid="content-handling-governance-alias">{aliasText(data.governanceAlias)}</p>
      {data.canEdit && !data.governanceAliases.length ? (
        <p className="admin-panel__hint" data-testid="content-handling-no-aliases">{NO_ALIASES_TEXT}</p>
      ) : null}
      {data.canEdit && (data.governanceAliases.length || data.governanceAlias) ? (
        <>
          <select className="admin-panel__input" value={alias ?? ""} aria-label="Governance alias" data-testid="content-handling-alias"
            disabled={saving} onChange={(event) => setAlias(event.target.value || null)}>
            <option value="">No governance alias</option>
            {data.governanceAliases.map((item) => <option key={item.alias} value={item.alias}>{item.label}</option>)}
          </select>
          {" "}
          <button type="button" className="admin-panel__action-btn" data-testid="content-handling-alias-save"
            disabled={saving || problem !== null || alias === data.governanceAlias} onClick={() => { void save(); }}>
            {saving ? "Saving…" : "Save"}
          </button>
          {problem ? <p className="admin-panel__hint" data-testid="content-handling-alias-problem">{problem}</p> : null}
        </>
      ) : null}
      <SaveMessage message={message} testId="content-handling-alias-message" />
    </div>
  );
}

function KindEditor({ workspaceId, kind, data, onSaved }: {
  workspaceId: string; kind: HandlingKind; data: ContentHandling; onSaved: (kind: HandlingKind) => void;
}) {
  const [choice, setChoice] = useState<HandlingChoice>(() => initialChoice(kind));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const problem = choiceProblem(choice, data);
  const preview = choiceUnchanged(choice, kind) ? [] : choicePreviewLines(choice, kind);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const saved = readHandlingKind(await readJson<unknown>(`${path(workspaceId)}/${encodeURIComponent(kind.kind)}`, {
        method: "PUT", body: JSON.stringify(choiceBody(choice)),
      }));
      if (!saved) throw new Error("the server's answer was not a content kind");
      onSaved(saved);
      setChoice(initialChoice(saved));
      setMessage({ ok: true, text: "Saved." });
    } catch (error) {
      setMessage({ ok: false, text: contentHandlingSaveErrorText(error) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-testid={`content-handling-edit-${kind.kind}`}>
      <select className="admin-panel__input" value={choice} aria-label={`Action for ${kind.label}`} data-testid={`content-handling-action-${kind.kind}`} disabled={saving}
        onChange={(event) => setChoice(event.target.value)}>
        <option value={DEFAULT_CHOICE}>{defaultOptionText(kind)}</option>
        {data.actions.map((action) => <option key={action} value={action}>{actionText(action)}</option>)}
      </select>
      {" "}
      <button type="button" className="admin-panel__action-btn" data-testid={`content-handling-save-${kind.kind}`}
        disabled={saving || problem !== null || choiceUnchanged(choice, kind)} onClick={() => { void save(); }}>
        {saving ? "Saving…" : "Save"}
      </button>
      {problem ? <p className="admin-panel__hint" data-testid={`content-handling-problem-${kind.kind}`}>{problem}</p> : null}
      {preview.length ? (
        <ul className="admin-panel__hint" data-testid={`content-handling-preview-${kind.kind}`}>
          {preview.map((line) => <li key={line}>{line}</li>)}
        </ul>
      ) : null}
      <SaveMessage message={message} testId={`content-handling-message-${kind.kind}`} />
    </div>
  );
}

// Where the kind's action in effect acts otherwise (e.g. credentials refused on the coding-agent gateway).
function SurfaceLines({ kind }: { kind: HandlingKind }) {
  const lines = surfaceDefaultLines(kind);
  if (!lines.length) return null;
  return (
    <ul className="admin-panel__hint" data-testid={`content-handling-surfaces-${kind.kind}`}>
      {lines.map((line) => <li key={line}>{line}</li>)}
    </ul>
  );
}

// Agents → Governance → Policy, "Sensitive content handling": per content kind the action in effect on model calls
// of this Workspace (with a "default" marker) and where it acts otherwise (per enforcement point), the shipped default,
// the fixed rules, and the Workspace's one governance alias every rerouting kind is sent to. Workspace admins and
// owners (the server's `can_edit`) change the alias and one kind at a time; everyone else reads it.
export function WorkspaceContentHandling({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<ContentHandling | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setData(null);
    setProblem(null);
    readJson<unknown>(path(workspaceId))
      .then((payload) => {
        if (!current) return;
        const read = readContentHandling(payload);
        setData(read);
        if (!read) setProblem("The server's answer was not a content handling setting.");
      })
      .catch((error) => { if (current) setProblem(contentHandlingLoadErrorText(error)); });
    return () => { current = false; };
  }, [workspaceId]);

  const replaceKind = (saved: HandlingKind) =>
    setData((before) => before && { ...before, kinds: before.kinds.map((kind) => (kind.kind === saved.kind ? saved : kind)) });
  const replaceAlias = (alias: string | null) => setData((before) => before && { ...before, governanceAlias: alias });

  return (
    <section className="admin-panel__card workspace-classification" aria-label="Sensitive content handling" data-testid="content-handling">
      <span className="workspace-classification__heading">Sensitive content handling</span>
      {problem ? <p className="work-area__error" role="alert" data-testid="content-handling-error">{problem}</p>
        : !data ? <p className="admin-panel__hint" role="status">Loading the sensitive content handling…</p> : (
          <>
            <p className="admin-panel__hint">What happens when a model call in this Workspace contains sensitive content.</p>
            <ul className="workspace-classification__lines" data-testid="content-handling-explanations">
              {ACTION_EXPLANATIONS.map((line) => <li key={line.action}>{line.text}</li>)}
            </ul>
            <GovernanceAlias workspaceId={workspaceId} data={data} onSaved={replaceAlias} />
            <div className="work-table-wrap">
              <table className="work-table" data-testid="content-handling-kinds">
                <thead>
                  <tr><th>Content kind</th><th>In effect</th><th>Shipped default</th>{data.canEdit ? <th>Change</th> : null}</tr>
                </thead>
                <tbody>
                  {data.kinds.map((kind) => (
                    <tr key={kind.kind} data-testid={`content-handling-kind-${kind.kind}`}>
                      <td>{kind.label}</td>
                      <td>
                        {effectiveText(kind, data.governanceAlias)}
                        {kind.isDefault ? <> <span className="work-badge work-badge--neutral" data-testid="content-handling-default">default</span></> : null}
                        <SurfaceLines kind={kind} />
                      </td>
                      <td>{actionText(kind.defaultAction)}</td>
                      {data.canEdit ? (
                        <td><KindEditor workspaceId={workspaceId} kind={kind} data={data} onSaved={replaceKind} /></td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.fixed.length ? (
              <>
                <span className="workspace-classification__heading">Always applied (not changeable)</span>
                <ul className="workspace-classification__lines" data-testid="content-handling-fixed">
                  {data.fixed.map((point) => (
                    <li key={point.surface}>
                      {point.label}
                      <ul>
                        {point.rules.map((rule) => <li key={rule.rule}>{rule.label}: {actionText(rule.action)}, always</li>)}
                      </ul>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            {data.canEdit ? null : <p className="admin-panel__hint" data-testid="content-handling-read-only">{READ_ONLY_TEXT}</p>}
          </>
        )}
    </section>
  );
}
