// The Workspace's structured-graph profile: the instance default or its own document, edited as a form
// for the common lists or as JSON. The server validates with the loader the build uses; saving re-extracts.
import { useCallback, useEffect, useState } from "react";
import { structuredProfileApi } from "./structuredGraphApi";
import type { StructuredProfileSettings } from "./structuredGraphApi";
import {
  applyForm, FILE_FORMATS, formatDocument, formOf, LINE_LISTS, parseDocument, RESET_CONFIRMATION, SAVE_CONFIRMATION,
} from "./structuredProfileModel";
import type { FileRule, ProfileForm } from "./structuredProfileModel";


type Message = { error: boolean; text: string } | null;

// The loaded settings, the JSON text and the form beside it, the last message and the busy flag.
function useStructuredProfile(workspaceId: string) {
  const [settings, setSettings] = useState<StructuredProfileSettings | null>(null);
  const [text, setText] = useState("");
  const [form, setForm] = useState<ProfileForm | null>(null);
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);

  const show = useCallback((next: StructuredProfileSettings) => {
    setSettings(next);
    setText(formatDocument(next.document));
    setForm(formOf(next.document));
  }, []);

  useEffect(() => {
    structuredProfileApi.get(workspaceId).then(show)
      .catch((err) => setMessage({ error: true, text: err instanceof Error ? err.message : String(err) }));
  }, [workspaceId, show]);

  return { settings, text, setText, form, setForm, message, setMessage, busy, setBusy, show };
}

type ProfileState = ReturnType<typeof useStructuredProfile>;

// Form and JSON edit the same document; validate and save send the parsed JSON (save asks first).
function profileEditor(workspaceId: string, state: ProfileState, form: ProfileForm) {
  const { text, setText, setForm, setMessage, setBusy, show } = state;
  const editForm = (next: ProfileForm) => {
    setForm(next);
    const parsed = parseDocument(text);
    if (!parsed.document) {
      setMessage({ error: true, text: `${parsed.error} Fix the JSON before using the form.` });
      return;
    }
    const applied = applyForm(parsed.document, next);
    setText(formatDocument(applied.document));
    setMessage(applied.error ? { error: true, text: applied.error } : null);
  };

  const editJson = (next: string) => {
    setText(next);
    const parsed = parseDocument(next);
    if (parsed.document) setForm(formOf(parsed.document));
    setMessage(parsed.error ? { error: true, text: parsed.error } : null);
  };

  const run = async (action: () => Promise<string>) => {
    setBusy(true);
    try {
      setMessage({ error: false, text: await action() });
    } catch (err) {
      setMessage({ error: true, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  };

  const current = () => {
    const parsed = parseDocument(text);
    if (!parsed.document) throw new Error(parsed.error ?? "Not a profile document.");
    return parsed.document;
  };

  const validate = () => run(async () => {
    const result = await structuredProfileApi.validate(workspaceId, current());
    return `Valid: this document builds as ${result.profile_id}.`;
  });

  const save = (document: Record<string, unknown> | null, confirmation: string) => run(async () => {
    if (!window.confirm(confirmation)) return "Not saved.";
    const saved = await structuredProfileApi.save(workspaceId, document);
    show(saved);
    return `Saved as ${saved.profile_id}; re-extraction of every layer is ${saved.build.state}.`;
  });

  const setRule = (index: number, rule: FileRule) =>
    editForm({ ...form, files: form.files.map((item, at) => (at === index ? rule : item)) });

  return { editForm, editJson, current, validate, save, setRule };
}

type Editor = ReturnType<typeof profileEditor>;

// The configuration file rules: glob, format, whether the manual documents it, and Remove; Add file rule below.
function FileRulesField({ form, editor }: { form: ProfileForm; editor: Editor }) {
  const { editForm, setRule } = editor;
  return (
    <div className="connector-field">
      <span>Configuration files</span>
      {form.files.map((rule, index) => (
        <div key={index} style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <input className="connector-field__input" aria-label={`File glob ${index + 1}`} value={rule.glob}
            onChange={(event) => setRule(index, { ...rule, glob: event.target.value })} />
          <select aria-label={`File format ${index + 1}`} value={rule.format}
            onChange={(event) => setRule(index, { ...rule, format: event.target.value })}>
            {FILE_FORMATS.map((format) => <option key={format} value={format}>{format}</option>)}
          </select>
          <label>
            <input type="checkbox" checked={rule.manual_documented}
              onChange={(event) => setRule(index, { ...rule, manual_documented: event.target.checked })} />
            {" "}judged against the manual
          </label>
          <button type="button" className="admin-panel__action-btn"
            onClick={() => editForm({ ...form, files: form.files.filter((_, at) => at !== index) })}>Remove</button>
        </div>
      ))}
      <button type="button" className="admin-panel__action-btn"
        onClick={() => editForm({ ...form, files: [...form.files, { glob: "", format: "ini", manual_documented: true }] })}>
        Add file rule
      </button>
    </div>
  );
}

function CommentPrefixesField({ form, editor }: { form: ProfileForm; editor: Editor }) {
  const { editForm } = editor;
  return (
    <div className="connector-field">
      <span>Comment characters per format <span className="admin-panel__muted">(separated by spaces)</span></span>
      {FILE_FORMATS.map((format) => (
        <label key={format} style={{ display: "flex", gap: "0.4rem" }}>
          <span style={{ minWidth: "6rem" }}>{format}</span>
          <input className="connector-field__input" value={form.commentPrefixes[format] ?? ""}
            onChange={(event) => editForm({ ...form, commentPrefixes: { ...form.commentPrefixes, [format]: event.target.value } })} />
        </label>
      ))}
    </div>
  );
}

function ProfileHistory({ history }: { history: StructuredProfileSettings["history"] }) {
  return (
    <details>
      <summary>Profile history</summary>
      <ul>
        {history.map((item) => (
          <li key={item.revision}>
            Revision {item.revision}: {item.reset ? "returned to the instance default" : item.profile_id}
            {item.created_at ? ` · ${item.created_at}` : ""}
          </li>
        ))}
      </ul>
    </details>
  );
}

// The form lists, the configuration files, comment characters, ticket patterns, the JSON and the actions.
function ProfileFields({ settings, form, text, readOnly, editor }: {
  settings: StructuredProfileSettings;
  form: ProfileForm;
  text: string;
  readOnly: boolean;
  editor: Editor;
}) {
  const { editForm, editJson, current, validate, save } = editor;
  return (
    <fieldset disabled={readOnly} style={{ border: "none", padding: 0 }} className="admin-panel__stack">
      <legend className="admin-panel__note">Common lists</legend>
      {LINE_LISTS.map((list) => (
        <label key={list.field} className="connector-field">
          <span>{list.label} <span className="admin-panel__muted">({list.hint}; one per line)</span></span>
          <textarea className="connector-field__input" rows={3} value={form[list.field] as string}
            onChange={(event) => editForm({ ...form, [list.field]: event.target.value })} />
        </label>
      ))}
      <FileRulesField form={form} editor={editor} />
      <CommentPrefixesField form={form} editor={editor} />
      <label className="connector-field">
        <span>Ticket patterns <span className="admin-panel__muted">(Type = regular expression; one per line)</span></span>
        <textarea className="connector-field__input" rows={3} value={form.ticketPatterns}
          onChange={(event) => editForm({ ...form, ticketPatterns: event.target.value })} />
      </label>
      <label className="connector-field">
        <span>Profile document (JSON)</span>
        <textarea className="connector-field__input" rows={18} spellCheck={false} value={text}
          style={{ fontFamily: "monospace" }} onChange={(event) => editJson(event.target.value)} />
      </label>
      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
        <button type="button" className="admin-panel__action-btn" onClick={() => void validate()}>Validate</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void save(current(), SAVE_CONFIRMATION)}>Save and re-extract</button>
        {settings.source === "workspace" ? (
          <button type="button" className="admin-panel__action-btn"
            onClick={() => void save(null, RESET_CONFIRMATION)}>Return to instance default</button>
        ) : null}
      </div>
    </fieldset>
  );
}

export function StructuredProfilePanel({ workspaceId }: { workspaceId: string }) {
  const state = useStructuredProfile(workspaceId);
  const { settings, form, text, message, busy } = state;

  if (!settings || !form) return <div className="admin-panel__hint">{message?.text ?? "Loading…"}</div>;
  const readOnly = !settings.may_author || busy;
  const editor = profileEditor(workspaceId, state, form);

  return (
    <section aria-label="Structured graph profile" className="admin-panel__stack">
      <h3>Extraction profile</h3>
      <p className="admin-panel__note">
        {settings.source === "workspace"
          ? `This workspace uses its own profile ${settings.profile_id} (revision ${settings.revision}).`
          : `This workspace uses the instance default profile ${settings.profile_id}.`}
        {" "}The profile is the vocabulary the rule-based extractors read: table headers (in every language the
        manuals use), configuration files, comment characters, variant files, placeholders and ticket numbers.
      </p>
      {!settings.may_author ? <p className="admin-panel__hint">Only a workspace admin or owner can change it.</p> : null}
      <ProfileFields settings={settings} form={form} text={text} readOnly={readOnly} editor={editor} />
      {message ? (
        <div className={message.error ? "admin-panel__error" : "admin-panel__note"} role={message.error ? "alert" : "status"}>
          {message.text}
        </div>
      ) : null}
      {settings.history.length ? <ProfileHistory history={settings.history} /> : null}
    </section>
  );
}
