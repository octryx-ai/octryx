import { useEffect, useRef, useState } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { saveDetectors } from "./detectorsApi";
import {
  CUSTOM_PREFIX, buildDetectorsBody, detectorIdFor, draftProblem, emptyDetector, readDetectorIssues, slugOf, upsertDetector, validDetectorId,
} from "./detectorsModel";
import type { CustomDetector, DetectorCatalog, DetectorCategory, DetectorIssue, DetectorRow, PreviewResult } from "./detectorsModel";
import type { EditTarget } from "./policyCatalogModel";
import { refusalText } from "./policyEngineVersions";
import { DetectorDefinition, DetectorFooter, DetectorRefusals, DetectorTest } from "./CustomDetectorParts";
import { NEW_CATEGORY, runDetectorPreview } from "./customDetectorPreview";

// The drawer's draft: the definition, its keywords text and new category, the test text with its preview, and the
// save state.
function useDetectorDraft(original: CustomDetector | null) {
  const [detector, setDetector] = useState<CustomDetector>(() => original ?? emptyDetector());
  const [idEdited, setIdEdited] = useState(original !== null);
  const [keywords, setKeywords] = useState(() => (original?.contextWords ?? []).join(", "));
  const [newCategory, setNewCategory] = useState<{ id: string; label: string } | null>(null);
  const [test, setTest] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [previewIssue, setPreviewIssue] = useState<string | null>(null);
  const [issues, setIssues] = useState<DetectorIssue[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const ticket = useRef(0);
  return {
    detector, setDetector, idEdited, setIdEdited, keywords, setKeywords, newCategory, setNewCategory, test, setTest, preview, setPreview,
    previewIssue, setPreviewIssue, issues, setIssues, problem, setProblem, busy, setBusy, confirmDelete, setConfirmDelete, ticket,
  };
}

type Draft = ReturnType<typeof useDetectorDraft>;

// Edits clear the last refusal; the name proposes the id until the id is edited; saving writes the whole list of
// custom detectors into the draft.
function detectorEditor(draft: Draft, { target, categories, onSaved }: {
  target: EditTarget | null;
  categories: DetectorCategory[];
  onSaved: (text: string) => Promise<void>;
}) {
  const { detector, setDetector, idEdited, setNewCategory, setProblem, setIssues, setBusy } = draft;
  const patch = (next: Partial<CustomDetector>) => { setDetector((current) => ({ ...current, ...next })); setProblem(null); setIssues([]); };
  const rename = (label: string) => patch({ label, id: detectorIdFor(label, detector.id, idEdited) });
  const pickCategory = (value: string) => {
    if (value === NEW_CATEGORY) { setNewCategory({ id: "", label: "" }); patch({ category: "" }); return; }
    setNewCategory(null);
    patch({ category: value });
  };
  const nameCategory = (label: string) => { const id = slugOf(label); setNewCategory({ id, label }); patch({ category: id }); };

  const write = async (list: CustomDetector[], done: string) => {
    if (!target) return;
    setBusy(true);
    setProblem(null);
    setIssues([]);
    try {
      await saveDetectors(target.version, buildDetectorsBody(list, categories), target.digest);
      await onSaved(done);
    } catch (error) {
      const found = readDetectorIssues(error);
      setIssues(found);
      setProblem(found.length ? null : refusalText(error));
    } finally {
      setBusy(false);
    }
  };
  const editId = (id: string) => { draft.setIdEdited(true); patch({ id: id.trim() }); };
  return { patch, rename, editId, pickCategory, nameCategory, write };
}

// One custom detector: its definition, a live test of the unsaved definition (the text is sent per request
// and never stored), and Save to draft / Delete through the same edit target as a policy edit. A draft in review
// is frozen, so the drawer is read-only then.
export function CustomDetectorDrawer({ row, catalog, target, workspaces, previewDelay = 400, onClose, onSaved }: {
  row: DetectorRow | null;
  catalog: DetectorCatalog;
  target: EditTarget | null;
  workspaces: { id: string; name: string }[];
  previewDelay?: number;
  onClose: () => void;
  onSaved: (text: string) => Promise<void>;
}) {
  const original = row?.custom ?? null;
  const draft = useDetectorDraft(original);
  const { detector, keywords, setKeywords, newCategory, test, setTest, preview, setPreview, previewIssue, setPreviewIssue, issues, problem,
    busy, confirmDelete, setConfirmDelete, ticket } = draft;

  const frozen = !target;
  const categories: DetectorCategory[] = newCategory ? [...catalog.categories, { ...newCategory, note: "", builtin: false }] : catalog.categories;
  const others = catalog.detectors.flatMap((item) => (item.custom && item.id !== original?.id ? [item.custom] : []));
  const blocked = frozen ? "The draft is in review and frozen." : draftProblem(detector, others, newCategory, catalog.categories);
  const usedBy = row?.usedBy ?? [];
  const previewId = validDetectorId(detector.id) ? detector.id : `${CUSTOM_PREFIX}preview`;

  useEffect(() => {
    return runDetectorPreview({ ticket, detector, previewId, test, categories, previewDelay, setPreview, setPreviewIssue });
    // `categories` derives from catalog + newCategory, which are listed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detector, previewId, test, catalog, newCategory, previewDelay]);

  const { patch, rename, editId, pickCategory, nameCategory, write } = detectorEditor(draft, { target, categories, onSaved });
  const save = () => (blocked ? undefined : void write(upsertDetector(others, detector, original?.id ?? null),
    `Saved the detector "${detector.label.trim()}" to the draft; it takes effect when the draft is published.`));
  const remove = () => void write(others, `Deleted the detector "${original?.label ?? ""}" from the draft; it stops finding when the draft is published.`);

  const eyebrow = `Custom detector · ${frozen ? "draft in review (frozen)" : target.createsDraft ? "creates a new draft" : `saved into draft v${target.version}`}`;
  const footer = (
    <DetectorFooter original={original} frozen={frozen} busy={busy} usedBy={usedBy} confirmDelete={confirmDelete} blocked={blocked}
      onDelete={() => (confirmDelete ? remove() : setConfirmDelete(true))} onClose={onClose} onSave={save} />
  );

  return (
    <SettingsDrawer eyebrow={eyebrow} title={original?.label || detector.label.trim() || "New custom detector"} size="detail" onClose={onClose} footer={footer}>
      <div data-testid="detector-drawer">
        {usedBy.length ? (
          <div className="policies__note" data-testid="detector-used-by">
            Used by {usedBy.length === 1 ? "1 policy" : `${usedBy.length} policies`}: {usedBy.join(", ")}. It cannot be deleted while a policy names it.
          </div>
        ) : null}
        {confirmDelete && !usedBy.length ? <div className="policies__warn" data-testid="detector-confirm-delete">Delete this detector from the draft? Press <b>Confirm delete</b>.</div> : null}
        <DetectorDefinition detector={detector} frozen={frozen} catalog={catalog} workspaces={workspaces} newCategory={newCategory}
          keywords={keywords} setKeywords={setKeywords} rename={rename} editId={editId} pickCategory={pickCategory}
          nameCategory={nameCategory} patch={patch} />
        <DetectorTest detector={detector} test={test} setTest={setTest} preview={preview} previewIssue={previewIssue} previewId={previewId} />
        <DetectorRefusals problem={problem} issues={issues} />
      </div>
    </SettingsDrawer>
  );
}
