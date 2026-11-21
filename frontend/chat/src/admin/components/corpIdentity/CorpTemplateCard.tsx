// One Office template inside a corporate identity profile: read view plus inline name/description editor.
import { type ChangeEvent, useState } from "react";
import type { OfficeTemplateEntry, OfficeTemplateType } from "../../types/adminPanelTypes.runtimeCorp";
import { DocTypeIcon, EditIcon } from "./corpIdentityIcons";
import "./corpIdentity.css";

export function HexSwatch({ hex }: { hex: string }) {
  // The swatch colour comes from the extracted brand data, so it stays inline.
  return <span className="corp-hex-swatch" style={{ background: hex }} />;
}

export const DOC_TYPE_LABELS: Record<OfficeTemplateType, string> = {
  pptx: "PowerPoint",
  docx: "Word",
  xlsx: "Excel",
};

type TemplateEditorProps = {
  nameDraft: string;
  setNameDraft: (value: string) => void;
  descDraft: string;
  setDescDraft: (value: string) => void;
  onSave: () => void;
  onCancel: () => void;
};

function TemplateEditor({ nameDraft, setNameDraft, descDraft, setDescDraft, onSave, onCancel }: TemplateEditorProps) {
  return (
    <div className="corp-panel">
      <input
        className="admin-panel__input corp-template__name-input"
        value={nameDraft}
        onChange={(e: ChangeEvent<HTMLInputElement>) =>
          setNameDraft(e.target.value)
        }
        placeholder="Template name"
      />
      <textarea
        className="admin-panel__textarea corp-template__desc-input"
        value={descDraft}
        onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
          setDescDraft(e.target.value)
        }
        placeholder="When to use this template (LLM guidance)…"
      />
      <div className="corp-row">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary corp-btn-xs"
          onClick={onSave}
        >
          Save
        </button>
        <button
          type="button"
          className="admin-panel__action-btn corp-btn-xs"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

type TemplateReadViewProps = { template: OfficeTemplateEntry; isBusy: boolean; onEdit: () => void; onDelete: () => void };

function TemplateReadView({ template, isBusy, onEdit, onDelete }: TemplateReadViewProps) {
  return (
    <div className="corp-template">
      <div className="corp-template__icon">
        <DocTypeIcon type={template.type} />
      </div>
      <div className="corp-template__main">
        <div className="corp-template__name">
          {template.display_name || template.source_file_name}
        </div>
        <div
          className={
            template.description
              ? "corp-template__file corp-template__file--with-desc"
              : "corp-template__file"
          }
        >
          {template.source_file_name}
        </div>
        {template.description ? (
          <div className="corp-template__desc">{template.description}</div>
        ) : null}
      </div>
      <div className="corp-template__actions">
        <button
          type="button"
          className={
            isBusy
              ? "admin-users__row-btn corp-row-btn--busy"
              : "admin-users__row-btn"
          }
          title="Edit name/description"
          onClick={onEdit}
        >
          <EditIcon />
        </button>
        <button
          type="button"
          className="admin-users__row-btn admin-users__row-btn--danger"
          title="Remove from profile"
          disabled={isBusy}
          onClick={onDelete}
        >
          ×
        </button>
      </div>
    </div>
  );
}

export function TemplateCard({
  template,
  isBusy,
  onUpdate,
  onDelete,
}: {
  template: OfficeTemplateEntry;
  isBusy: boolean;
  onUpdate: (
    updates: Partial<{ display_name: string; description: string }>,
  ) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState(template.display_name || "");
  const [descDraft, setDescDraft] = useState(template.description || "");

  const handleSave = () => {
    onUpdate({
      display_name: nameDraft.trim() || template.display_name,
      description: descDraft.trim(),
    });
    setEditing(false);
  };

  if (editing) {
    return (
      <TemplateEditor nameDraft={nameDraft} setNameDraft={setNameDraft} descDraft={descDraft} setDescDraft={setDescDraft}
        onSave={handleSave} onCancel={() => setEditing(false)} />
    );
  }

  return (
    <TemplateReadView
      template={template}
      isBusy={isBusy}
      onEdit={() => {
        setNameDraft(template.display_name || "");
        setDescDraft(template.description || "");
        setEditing(true);
      }}
      onDelete={onDelete}
    />
  );
}
