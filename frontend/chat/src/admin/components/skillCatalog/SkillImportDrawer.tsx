import { useState } from "react";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { SkillImportGit } from "./SkillImportGit";
import { SkillImportResults } from "./SkillImportResults";
import { SkillImportUpload } from "./SkillImportUpload";
import { importFromGit, importUpload, inspectSource, loadSources } from "./skillCatalogApi";
import { refusalText } from "./skillCatalogModel";
import type { CategoryCatalog } from "./skillCatalogTypes";
import type { InspectResult, SourceRow } from "./skillDeliveryTypes";
import {
  defaultSelection, gitImportBody, importLabel, importedIds, inspectBody, selectedItems, splitTags, uploadIssue,
} from "./skillImportModel";
import type { GitRequest, ImportMode, TrackingMode, Trust } from "./skillImportModel";
import "./skillEditor.css";

const MODES: { id: ImportMode; label: string }[] = [
  { id: "upload", label: "Upload" },
  { id: "git", label: "Git repository" },
  { id: "market", label: "Marketplace" },
];
const EMPTY_REQUEST: GitRequest = { url: "", ref: "", path: "", marketplacePlugin: "" };

// The drawer's state, in the order the drawer has always declared it.
function useSkillImportState() {
  const [mode, setMode] = useState<ImportMode>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [request, setRequest] = useState<GitRequest>(EMPTY_REQUEST);
  const [result, setResult] = useState<InspectResult | null>(null);
  const [source, setSource] = useState<SourceRow | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [categoryId, setCategoryId] = useState("");
  const [tags, setTags] = useState("");
  const [tracking, setTracking] = useState<TrackingMode>("pinned");
  const [trust, setTrust] = useState<Trust | "">("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  return {
    mode, setMode, file, setFile, request, setRequest, result, setResult, source, setSource, selected, setSelected, categoryId, setCategoryId,
    tags, setTags, tracking, setTracking, trust, setTrust, busy, setBusy, problem, setProblem,
  };
}

// The drawer's steps: switch mode, upload, inspect a repository, import the inspected commit.
function skillImportSteps(state: ReturnType<typeof useSkillImportState>, onImported: (skillIds: string[]) => void) {
  const {
    mode, setMode, file, request, setRequest, result, setResult, source, setSource, selected, setSelected, categoryId, tags, setTracking,
    tracking, trust, setBusy, setProblem,
  } = state;
  const switchMode = (next: ImportMode) => {
    setMode(next);
    setResult(null);
    setSelected([]);
    setProblem(null);
    setRequest(EMPTY_REQUEST);
  };

  const act = async (action: () => Promise<void>) => {
    setBusy(true);
    setProblem(null);
    try {
      await action();
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
    }
  };

  const upload = () => {
    const issue = uploadIssue(file) ?? (categoryId ? null : "Choose a category.");
    if (issue || !file) {
      setProblem(issue);
      return;
    }
    void act(async () => onImported(importedIds(await importUpload(file, categoryId, splitTags(tags)))));
  };

  const inspect = () => act(async () => {
    const inspected = (await inspectSource(inspectBody(request, mode))) as InspectResult;
    setResult(inspected);
    setSelected(defaultSelection(inspected));
    setTracking("pinned");
    const known = await loadSources().catch(() => null) as { sources?: SourceRow[] } | null;
    setSource(known?.sources?.find((row) => row.url === inspected.url) ?? null);
  });

  const importGit = () => {
    if (!result) return;
    if (!categoryId) {
      setProblem("Choose a category.");
      return;
    }
    const body = gitImportBody(request, result, selected, {
      categoryId, tracking, trust: source ? "" : trust || "community", tags: splitTags(tags),
    });
    void act(async () => onImported(importedIds(await importFromGit(body))));
  };

  return { switchMode, upload, inspect, importGit };
}

function useSkillImport(onImported: (skillIds: string[]) => void) {
  const state = useSkillImportState();
  return { ...state, ...skillImportSteps(state, onImported) };
}

type SkillImport = ReturnType<typeof useSkillImport>;

// Import skills into the catalog (mock `renderImport` + `#drawer-import`): an upload (SKILL.md or .zip), a Git
// repository, or a plugin marketplace entry. Git and marketplace imports inspect first (read-only, one commit) and
// then import exactly that commit; every import becomes a draft that a second admin publishes.
export function SkillImportDrawer({ categories, onClose, onImported }: {
  categories: CategoryCatalog;
  onClose: () => void;
  onImported: (skillIds: string[]) => void;
}) {
  const state = useSkillImport(onImported);
  const { mode, file, request, result, source, selected, categoryId, tags, tracking, trust, busy, problem } = state;

  return (
    <SettingsDrawer eyebrow="Skills" title="Import skill" size="detail" onClose={onClose} footer={<ImportFooter state={state} onClose={onClose} />}>
      <div className="skills__import" data-testid="skill-import-drawer">
        <SegmentedTabs size="small" label="Import from" idPrefix="skill-import" value={mode}
          onChange={(key) => state.switchMode(key as ImportMode)}
          tabs={MODES.map((item) => ({ key: item.id, label: item.label, disabled: busy, testId: `skill-import-mode-${item.id}` }))} />
        {problem ? <p className="policies__warn" role="alert" data-testid="skill-import-problem">{problem}</p> : null}
        {mode === "upload" ? (
          <SkillImportUpload file={file} categoryId={categoryId} tags={tags} categories={categories}
            onFile={state.setFile} onCategory={state.setCategoryId} onTags={state.setTags} />
        ) : result ? (
          <SkillImportResults result={result} source={source} selected={selected} categoryId={categoryId} tags={tags}
            tracking={tracking} trust={trust} categories={categories}
            onToggle={(key) => state.setSelected((current) => (current.includes(key) ? current.filter((entry) => entry !== key) : [...current, key]))}
            onCategory={state.setCategoryId} onTags={state.setTags} onTracking={state.setTracking} onTrust={state.setTrust} />
        ) : (
          <SkillImportGit mode={mode} request={request} onChange={(change) => state.setRequest((current) => ({ ...current, ...change }))} />
        )}
      </div>
    </SettingsDrawer>
  );
}

// Upload: Cancel and Import as draft. Git and marketplace: Cancel and Inspect, then Back and the import of the selection.
function ImportFooter({ state, onClose }: { state: SkillImport; onClose: () => void }) {
  const { mode, file, request, result, selected, categoryId, busy } = state;
  const chosen = selectedItems(result, selected);
  const cancel = <button type="button" className="admin-panel__action-btn" onClick={onClose} disabled={busy}>Cancel</button>;
  const primary = (label: string, onClick: () => void, disabled: boolean, testId: string) => (
    <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid={testId}
      disabled={busy || disabled} onClick={onClick}>{label}</button>
  );
  return mode === "upload" ? (
    <>{cancel}{primary(busy ? "Importing…" : "Import as draft", state.upload, !file || !categoryId, "skill-import-upload")}</>
  ) : result ? (
    <>
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => { state.setResult(null); state.setProblem(null); }}>Back</button>
      {primary(busy ? "Importing…" : importLabel(chosen), state.importGit, !chosen.length || !categoryId, "skill-import-git")}
    </>
  ) : (
    <>{cancel}{primary(busy ? "Inspecting…" : "Inspect", () => void state.inspect(),
      !request.url.trim() || (mode === "market" && !request.marketplacePlugin.trim()), "skill-import-inspect")}</>
  );
}
