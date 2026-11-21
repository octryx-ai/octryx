import { classLabel } from "./agentsWorkflows/awBadges";
import { useCallback, useEffect, useState } from "react";
import { readJson } from "../utils/adminPanelHelpers";
import {
  DEFAULT_TOOL_SETS_PATH,
  type DefaultToolSet,
  type DefaultToolSetsView,
  parseDefaultToolSets,
} from "./defaultToolSets";
import {
  familiesToText,
  refusalText,
  textToFamilies,
  writePolicyList,
} from "./policyLists";
import "./workflowSurfaces/areaPurpose.css";

type LoadState =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "loaded"; view: DefaultToolSetsView };

const META_STYLE = { fontSize: "var(--ds-text-xs)", color: "var(--text-muted)" };

function DefaultToolSetCard({
  set,
  onChanged,
}: {
  set: DefaultToolSet;
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const write = (method: "PUT" | "POST") =>
    writeToolSet(method, { set, draft, setBusy, setError, setDraft, onChanged });

  return (
    <div
      className="connector-policy__catalog-item"
      style={{ display: "block" }}
    >
      <SetHeader set={set} editing={draft !== null} busy={busy} onEdit={() => setDraft(familiesToText(set.families))}
        onReset={() => void write("POST")} />
      <div className="connector-tool__desc">{set.description}</div>
      {draft === null ? (
        set.families.map((family) => (
          <div
            key={family.name}
            style={{ fontSize: "var(--ds-text-xs)", marginTop: "0.25rem" }}
          >
            <span style={{ color: "var(--text-secondary)" }}>
              {family.name}:
            </span>{" "}
            <code style={{ whiteSpace: "normal" }}>
              {family.tools.join(", ")}
            </code>
          </div>
        ))
      ) : (
        <SetEditor set={set} draft={draft} setDraft={setDraft} busy={busy} onSave={() => void write("PUT")}
          onCancel={() => {
            setDraft(null);
            setError("");
          }} />
      )}
      <SetNotes set={set} error={error} />
    </div>
  );
}

type WriteDeps = {
  set: DefaultToolSet;
  draft: string | null;
  setBusy: (busy: boolean) => void;
  setError: (error: string) => void;
  setDraft: (draft: string | null) => void;
  onChanged: () => void;
};

async function writeToolSet(method: "PUT" | "POST", { set, draft, setBusy, setError, setDraft, onChanged }: WriteDeps) {
  setBusy(true);
  setError("");
  const path = `${DEFAULT_TOOL_SETS_PATH}/${encodeURIComponent(set.capabilityType)}`;
  const result =
    method === "PUT"
      ? await writePolicyList(path, "PUT", {
          families: textToFamilies(draft ?? ""),
          expected_version: set.version || undefined,
        })
      : await writePolicyList(`${path}/reset`, "POST");
  setBusy(false);
  if (!result.ok) {
    setError(
      result.refusal
        ? refusalText(result.refusal)
        : `Request failed (${result.status}).`,
    );
    return;
  }
  setDraft(null);
  onChanged();
}

function SetHeader({
  set,
  editing,
  busy,
  onEdit,
  onReset,
}: {
  set: DefaultToolSet;
  editing: boolean;
  busy: boolean;
  onEdit: () => void;
  onReset: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: "0.5rem",
        alignItems: "baseline",
        flexWrap: "wrap",
      }}
    >
      <div className="connector-tool__name">
        {set.capabilityClasses.map((value) => classLabel(value)).join(" · ") || set.title}
      </div>
      <code style={{ fontSize: "var(--ds-text-xs)" }}>{set.key}</code>
      <span style={META_STYLE}>
        {set.capabilityType} · {set.toolCount} tools ·{" "}
        {set.matchesSeed
          ? `seed ${set.seedKey}`
          : `edited (seed ${set.seedKey})`}
      </span>
      {!editing && (
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onEdit}
        >
          Edit
        </button>
      )}
      {!set.matchesSeed && !editing && (
        <button
          type="button"
          className="admin-panel__action-btn"
          disabled={busy}
          onClick={onReset}
        >
          Reset to seed
        </button>
      )}
    </div>
  );
}

function SetEditor({
  set,
  draft,
  setDraft,
  busy,
  onSave,
  onCancel,
}: {
  set: DefaultToolSet;
  draft: string;
  setDraft: (draft: string) => void;
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div style={{ marginTop: "0.4rem" }}>
      <p className="admin-panel__hint">
        One family per line: <code>family: tool, tool</code>. The order is
        the priority under a provider cap. Saving creates the next version.
      </p>
      <textarea
        className="connector-field__input"
        rows={Math.min(14, set.families.length + 3)}
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
          onClick={onSave}
        >
          Save as next version
        </button>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function SetNotes({ set, error }: { set: DefaultToolSet; error: string }) {
  return (
    <>
      {error && (
        <div className="admin-panel__error" role="alert">
          {error}
        </div>
      )}
      {set.unregisteredTools.length > 0 && (
        <div style={{ fontSize: "var(--ds-text-xs)", marginTop: "0.25rem" }} role="alert">
          Not in the {set.capabilityType} catalog:{" "}
          <code>{set.unregisteredTools.join(", ")}</code>
        </div>
      )}
      {set.history.length > 0 && (
        <div style={{ ...META_STYLE, marginTop: "0.25rem" }}>
          History:{" "}
          {set.history
            .map(
              (entry) =>
                `${entry.key} (${entry.action.replace("policy_list.", "")})`,
            )
            .join(" · ")}
        </div>
      )}
    </>
  );
}


/** "Default tool sets (governed)": the curated set each capability class offers by default. */
export function AdminDefaultToolSetsSection() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(() => {
    readJson<unknown>(DEFAULT_TOOL_SETS_PATH)
      .then((payload) =>
        setState({ status: "loaded", view: parseDefaultToolSets(payload) }),
      )
      .catch(() => setState({ status: "failed" }));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Collapsed below the catalog: the sets are long, edited rarely and read-only by default.
  return (
    <details className="area-disclosure">
      <summary className="area-disclosure__summary">
        Default tool sets (governed)
        {state.status === "loaded" ? ` · ${state.view.sets.length} sets` : ""}
      </summary>
      <div className="area-disclosure__body">
        <p className="admin-panel__hint">
          The tools a turn gets when no workflow is selected, per capability class.
        </p>
        {state.status === "loading" && (
          <div className="admin-panel__empty-state">
            Loading default tool sets…
          </div>
        )}
        {state.status === "failed" && (
          <div className="admin-panel__empty-state">
            The default tool sets could not be loaded.
          </div>
        )}
        {state.status === "loaded" &&
          // Only the sets a run capability class uses.
          state.view.sets.filter((set) => set.capabilityClasses.length > 0).map((set) => (
            <DefaultToolSetCard
              key={set.capabilityType}
              set={set}
              onChanged={load}
            />
          ))}
      </div>
    </details>
  );
}
