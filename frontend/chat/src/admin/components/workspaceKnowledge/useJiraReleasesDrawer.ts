import { useCallback, useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { ConnectorRequestError, reasonText } from "./connectorReasons";
import { connectorsApi } from "./connectorsApi";
import type { SourceConnector } from "./connectorTypes";
import { releaseCodeText } from "./jiraReleasesContract";
import { checkDraft, draftFromBlock, isDirty, releasesPayload } from "./jiraReleasesModel";
import type { FieldErrors, ReleasesDraft } from "./jiraReleasesModel";

export type Phase = "loading" | "ready" | "missing" | "load_failed";
export type Banner = { kind: "error" | "success"; code?: string; text: string } | null;

type Setter<T> = Dispatch<SetStateAction<T>>;
type Loaded = { setConnector: Setter<SourceConnector | null>; setDraft: Setter<ReleasesDraft>; setPhase: Setter<Phase>; setBanner: Setter<Banner> };

// Reloads the connector on open, because the PUT replaces the whole configuration. Returns the effect's cleanup.
function loadReleasesConnector(workspaceId: string, connectorKey: string, set: Loaded): () => void {
  let live = true;
  connectorsApi.list(workspaceId)
    .then((listing) => {
      if (!live) return;
      const found = listing.connectors.find((item) => item.connector_key === connectorKey && item.kind === "jira");
      set.setConnector(found ?? null);
      set.setDraft(draftFromBlock(found?.scope.releases));
      set.setPhase(found ? "ready" : "missing");
    })
    .catch((err: unknown) => {
      if (!live) return;
      set.setBanner({ kind: "error", text: err instanceof Error ? err.message : String(err) });
      set.setPhase("load_failed");
    });
  return () => { live = false; };
}

type SaveContext = Loaded & {
  workspaceId: string; connectorKey: string; connector: SourceConnector | null; draft: ReleasesDraft; onSaved: () => void;
  setAttempted: Setter<boolean>; setServerErrors: Setter<FieldErrors>; setSaving: Setter<boolean>;
};

function savedBanner(stored: SourceConnector): Banner {
  const sync = stored.release_sync;
  return {
    kind: "success",
    text: sync?.state === "active" ? "Saved. Release sync is active; the next run syncs the mapped projects' versions."
      : sync?.state === "needs_configuration" ? `Saved. Release sync needs configuration: ${releaseCodeText(sync.reason ?? "")}.`
        : "Saved. Release sync is off for this connector.",
  };
}

function refusedSave(err: unknown, ctx: SaveContext) {
  if (err instanceof ConnectorRequestError && err.field && err.reason) {
    ctx.setServerErrors({ [err.field]: err.reason });
    ctx.setBanner({ kind: "error", code: err.reason, text: `The server refused ${err.field}.` });
  } else if (err instanceof ConnectorRequestError && err.reason) {
    ctx.setBanner({ kind: "error", code: err.reason, text: `The server refused the save: ${reasonText(err.reason)}.` });
  } else {
    ctx.setBanner({ kind: "error", text: err instanceof Error ? err.message : String(err) });
  }
}

async function saveReleases(ctx: SaveContext) {
  const { connector, draft } = ctx;
  if (!connector) return;
  ctx.setAttempted(true);
  if (Object.keys(checkDraft(draft)).length) {
    ctx.setBanner({ kind: "error", text: "Fix the marked fields before saving." });
    return;
  }
  ctx.setSaving(true);
  ctx.setBanner(null);
  try {
    const stored = await connectorsApi.configure(ctx.workspaceId, ctx.connectorKey, releasesPayload(connector, draft));
    ctx.setConnector(stored);
    ctx.setDraft(draftFromBlock(stored.scope.releases));
    ctx.setAttempted(false);
    ctx.setServerErrors({});
    ctx.setBanner(savedBanner(stored));
    ctx.onSaved();
  } catch (err) {
    refusedSave(err, ctx);
  } finally {
    ctx.setSaving(false);
  }
}

// The drawer's state: the loaded connector, the draft, client and server errors, the banner and the discard step.
export function useJiraReleasesDrawer(workspaceId: string, connectorKey: string, onClose: () => void, onSaved: () => void) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [connector, setConnector] = useState<SourceConnector | null>(null);
  const [draft, setDraft] = useState<ReleasesDraft>(() => draftFromBlock(null));
  const [attempted, setAttempted] = useState(false);
  const [serverErrors, setServerErrors] = useState<FieldErrors>({});
  const [banner, setBanner] = useState<Banner>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  useEffect(
    () => loadReleasesConnector(workspaceId, connectorKey, { setConnector, setDraft, setPhase, setBanner }),
    [workspaceId, connectorKey],
  );

  const saved = connector?.scope.releases ?? null;
  const dirty = connector !== null && isDirty(draft, saved);
  const clientErrors = useMemo(() => (attempted ? checkDraft(draft) : {}), [attempted, draft]);
  const errors = { ...clientErrors, ...serverErrors };

  // Any edit invalidates the server's refusal: its path indexes described the rows as they were sent.
  const edit = (patch: Partial<ReleasesDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setServerErrors({});
    setBanner(null);
    setConfirmDiscard(false);
  };

  const close = useCallback(() => {
    if (dirty && !confirmDiscard) setConfirmDiscard(true);
    else onClose();
  }, [dirty, confirmDiscard, onClose]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  const save = () => saveReleases({
    workspaceId, connectorKey, connector, draft, onSaved, setConnector, setDraft, setPhase, setBanner, setAttempted, setServerErrors, setSaving,
  });

  return { phase, connector, draft, serverErrors, banner, saving, confirmDiscard, setConfirmDiscard, saved, dirty, errors, edit, close, save };
}
