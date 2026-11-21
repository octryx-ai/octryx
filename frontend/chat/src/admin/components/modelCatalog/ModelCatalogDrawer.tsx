import { useState } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import type { ContentCategory } from "../providerTab/litellmGatewayApprovedCategories";
import { saveCatalogModel } from "./modelCatalogApi";
import {
  catalogPatch,
  draftFromRow,
  draftProblems,
  isClearanceRaise,
  readCatalogRow,
  saveErrorText,
} from "./modelCatalogContract";
import type { CatalogRow, ModelDraft } from "./modelCatalogContract";
import { CostTab, DataTab, GeneralTab, GenerationTab } from "./ModelCatalogTabs";

const TABS = [
  { id: "general", label: "General" },
  { id: "data", label: "Data" },
  { id: "generation", label: "Generation" },
  { id: "cost", label: "Cost" },
] as const;
type TabId = (typeof TABS)[number]["id"];

type Props = {
  row: CatalogRow;
  levels: string[];
  categories: ContentCategory[];
  onClose: () => void;
  onSaved: (row: CatalogRow) => void;
};

// The model side panel: one save for all four tabs; only changed fields are sent.
export function ModelCatalogDrawer({ row, levels, categories, onClose, onSaved }: Props) {
  const [tab, setTab] = useState<TabId>("general");
  const [draft, setDraft] = useState<ModelDraft>(() => draftFromRow(row));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const onDraft = (patch: Partial<ModelDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setError("");
  };
  const patch = catalogPatch(row, draft);
  const problems = draftProblems(draft, row);
  const raise = isClearanceRaise(row, draft, levels);

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const saved = readCatalogRow(await saveCatalogModel(row.id, patch));
      if (saved) onSaved(saved);
      onClose();
    } catch (failure) {
      setError(saveErrorText(failure));
    } finally {
      setSaving(false);
    }
  };

  return (
    <SidePanel
      title={row.displayName}
      subtitle={row.provider.displayName || "Model"}
      onClose={onClose}
      testId="catalog-panel"
      tabs={{
        tabs: TABS.map((item) => ({ key: item.id, label: item.label })),
        value: tab,
        onChange: (key) => setTab(key as TabId),
        label: "Model settings",
        idPrefix: "catalog",
        testId: "catalog-tabs",
      }}
      footer={
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
            data-testid="catalog-save" disabled={saving || problems.length > 0 || !Object.keys(patch).length}
            onClick={() => void save()}>
            {saving ? "Saving…" : "Save model"}
          </button>
        </>
      }
    >
      {tab === "general" ? <GeneralTab row={row} draft={draft} onDraft={onDraft} /> : null}
      {tab === "data" ? <DataTab row={row} draft={draft} onDraft={onDraft} levels={levels} categories={categories} /> : null}
      {tab === "generation" ? <GenerationTab row={row} draft={draft} onDraft={onDraft} /> : null}
      {tab === "cost" ? <CostTab row={row} draft={draft} onDraft={onDraft} /> : null}
      {raise ? (
        <p className="model-catalog__warn" role="status">
          Raising the clearance lets this model see more sensitive data. It applies when you save and is recorded in
          the audit log.
        </p>
      ) : null}
      {problems.map((problem) => <p key={problem} className="admin-panel__error">{problem}</p>)}
      {error ? <p className="admin-panel__error" role="alert">{error}</p> : null}
    </SidePanel>
  );
}
