import { useCallback, useEffect, useState } from "react";
import { readJson } from "../utils/adminPanelHelpers";
import {
  POLICY_LISTS_PATH,
  type PolicyListState,
  asNames,
  labelledToText,
  parsePolicyLists,
  refusalText,
  settingsToText,
  textToLabelled,
  textToNames,
  textToSettings,
  writePolicyList,
} from "./policyLists";

type Codec = {
  hint: string;
  toText: (values: unknown[], list: PolicyListState) => string;
  fromText: (text: string) => unknown;
};

// How each list is edited as plain text, one entry per line.
const CODECS: Record<string, Codec> = {
  weak_coding_model_families: {
    hint: "One model family per line (matched as part of the model id).",
    toText: (values) => asNames(values).join("\n"),
    fromText: textToNames,
  },
  model_capabilities: {
    hint: "One capability per line: key: label.",
    toText: (values) => labelledToText(values, "key"),
    fromText: (text) => textToLabelled(text, "key"),
  },
  // A settings record, edited as `field: value` lines.
  workflow_proposal_settings: {
    hint: "timeout_seconds: 1-60.",
    toText: (_values, list) => settingsToText(list.settings),
    fromText: textToSettings,
  },
};

type PolicyListHeaderProps = {
  list: PolicyListState;
  codec: Codec;
  draft: string | null;
  busy: boolean;
  setDraft: (draft: string | null) => void;
  write: (reset: boolean) => Promise<void>;
};

function PolicyListHeader({ list, codec, draft, busy, setDraft, write }: PolicyListHeaderProps) {
  return (
    <div
      style={{
        display: "flex",
        gap: "0.5rem",
        alignItems: "baseline",
        flexWrap: "wrap",
      }}
    >
      <div className="connector-tool__name">{list.title}</div>
      <code style={{ fontSize: "var(--ds-text-xs)" }}>{list.key}</code>
      <span style={{ fontSize: "var(--ds-text-xs)", color: "var(--text-muted)" }}>
        {list.matchesSeed
          ? `seed ${list.seedKey}`
          : `edited (seed ${list.seedKey})`}
        {list.recordState === "unreadable"
          ? " · stored record unreadable, seed live"
          : ""}
      </span>
      {draft === null && (
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => setDraft(codec.toText(list.values, list))}
        >
          Edit
        </button>
      )}
      {draft === null && !list.matchesSeed && (
        <button
          type="button"
          className="admin-panel__action-btn"
          disabled={busy}
          onClick={() => void write(true)}
        >
          Reset to seed
        </button>
      )}
    </div>
  );
}

type PolicyListEditorProps = {
  list: PolicyListState;
  codec: Codec;
  draft: string;
  busy: boolean;
  setDraft: (draft: string | null) => void;
  setError: (error: string) => void;
  write: (reset: boolean) => Promise<void>;
};

function PolicyListEditor({ list, codec, draft, busy, setDraft, setError, write }: PolicyListEditorProps) {
  return (
    <div style={{ marginTop: "0.4rem" }}>
      <p className="admin-panel__hint">{codec.hint}</p>
      <textarea
        className="connector-field__input"
        rows={Math.min(16, list.values.length + 3)}
        style={{
          width: "100%",
          fontFamily: "monospace",
          fontSize: "var(--ds-text-xs)",
        }}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <div className="admin-panel__form-actions">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={busy}
          onClick={() => void write(false)}
        >
          Save as next version
        </button>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => {
            setDraft(null);
            setError("");
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function PolicyListCard({
  list,
  onChanged,
}: {
  list: PolicyListState;
  onChanged: () => void;
}) {
  const codec = CODECS[list.listId];
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!codec) return null;

  const write = async (reset: boolean) => {
    setBusy(true);
    setError("");
    const path = `${POLICY_LISTS_PATH}/${encodeURIComponent(list.listId)}`;
    const result = reset
      ? await writePolicyList(`${path}/reset`, "POST")
      : await writePolicyList(path, "PUT", {
          values: codec.fromText(draft ?? ""),
          expected_version: list.version,
        });
    setBusy(false);
    if (!result.ok) {
      setError(result.refusal ? refusalText(result.refusal) : `Request failed (${result.status}).`);
      return;
    }
    setDraft(null);
    onChanged();
  };

  return (
    <div className="connector-policy__catalog-item" style={{ display: "block" }}>
      <PolicyListHeader list={list} codec={codec} draft={draft} busy={busy} setDraft={setDraft} write={write} />
      <div className="connector-tool__desc">{list.description}</div>
      {list.pinned.length > 0 && (
        <div style={{ fontSize: "var(--ds-text-xs)" }}>
          Pinned by code (cannot be removed):{" "}
          <code>{list.pinned.join(", ")}</code>
        </div>
      )}
      {draft === null ? (
        <pre style={{ fontSize: "var(--ds-text-xs)", whiteSpace: "pre-wrap", margin: "0.3rem 0" }}>
          {codec.toText(list.values, list)}
        </pre>
      ) : (
        <PolicyListEditor list={list} codec={codec} draft={draft} busy={busy} setDraft={setDraft} setError={setError} write={write} />
      )}
      {error && (
        <div className="admin-panel__error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

/** "Policy lists (governed)": admin-editable product policy with a code seed. */
export function AdminPolicyListsSection() {
  const [lists, setLists] = useState<PolicyListState[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(() => {
    readJson<unknown>(POLICY_LISTS_PATH)
      .then((payload) => {
        setLists(parsePolicyLists(payload));
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="admin-panel__subsection" style={{ marginTop: "1rem" }}>
      <div
        className="admin-panel__section-header"
        style={{ marginBottom: "0.5rem" }}
      >
        <span>Policy lists (governed)</span>
      </div>
      <p className="admin-panel__hint">
        Product policy with a code seed: weak coding model families, the model
        capability catalog for runtime tags and workflow requirements, the
        diagram types the diagram decision offers, and the workflow proposal
        settings (timeout). Each edit is
        validated, stored as the next version and audited.
      </p>
      {failed && (
        <div className="admin-panel__empty-state">
          The policy lists could not be loaded.
        </div>
      )}
      {lists?.map((list) => (
        <PolicyListCard key={list.listId} list={list} onChanged={load} />
      ))}
    </div>
  );
}
