import { useRef, useState } from "react";
import type { AdminOfficeTemplateEntry } from "../types/adminPanelTypes.runtimeCorp";

type UseAdminOfficeTemplatesArgs = {
  sanitizeTemplateKey: (value: string) => string;
};

export function useAdminOfficeTemplates({
  sanitizeTemplateKey,
}: UseAdminOfficeTemplatesArgs) {
  const [runtimeOfficeTemplatesDraft, setRuntimeOfficeTemplatesDraft] =
    useState<AdminOfficeTemplateEntry[]>([]);
  const [runtimeOfficeTemplateUploadBusy, setRuntimeOfficeTemplateUploadBusy] =
    useState(false);
  const officeTemplateFileInputRef = useRef<HTMLInputElement | null>(null);

  const handleAddOfficeTemplateDraft = () => {
    setRuntimeOfficeTemplatesDraft((current) => [
      ...current,
      {
        key: `template-${current.length + 1}`,
        name: "",
        doc_type: "pptx",
        path: "",
        description: "",
        is_default: false,
      },
    ]);
  };

  const handlePatchOfficeTemplateDraft = (
    index: number,
    patch: Partial<AdminOfficeTemplateEntry>,
  ) => {
    setRuntimeOfficeTemplatesDraft((current) =>
      current.map((item, itemIndex) => {
        if (itemIndex !== index) {
          if (!patch.is_default || item.doc_type !== current[index]?.doc_type) {
            return item;
          }
          return { ...item, is_default: false };
        }
        const next = { ...item, ...patch };
        if (patch.key != null) {
          next.key = sanitizeTemplateKey(String(patch.key));
        }
        return next;
      }),
    );
  };

  const handleRemoveOfficeTemplateDraft = (index: number) => {
    setRuntimeOfficeTemplatesDraft((current) =>
      current.filter((_, itemIndex) => itemIndex !== index),
    );
  };

  const handleUploadOfficeTemplate = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    setRuntimeOfficeTemplateUploadBusy(true);
    try {
      const response = await fetch(
        "/admin/chat/api/panel/office-templates/upload",
        {
          method: "POST",
          credentials: "same-origin",
          body: form,
        },
      );
      if (!response.ok) {
        let detail = response.statusText;
        try {
          const payload = (await response.json()) as { detail?: string };
          detail = payload.detail || detail;
        } catch {
          // Keep status text fallback.
        }
        throw new Error(detail || "Template upload failed");
      }
      const payload = (await response.json()) as {
        template: AdminOfficeTemplateEntry;
      };
      setRuntimeOfficeTemplatesDraft((current) => [
        ...current,
        payload.template,
      ]);
    } finally {
      setRuntimeOfficeTemplateUploadBusy(false);
      if (officeTemplateFileInputRef.current) {
        officeTemplateFileInputRef.current.value = "";
      }
    }
  };

  return {
    handleAddOfficeTemplateDraft,
    handlePatchOfficeTemplateDraft,
    handleRemoveOfficeTemplateDraft,
    handleUploadOfficeTemplate,
    officeTemplateFileInputRef,
    runtimeOfficeTemplateUploadBusy,
    runtimeOfficeTemplatesDraft,
    setRuntimeOfficeTemplatesDraft,
  };
}
