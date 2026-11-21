// Composer attachment handlers: upload draft files and remove a draft attachment.
import type {
  ComposerInteractionHandlers,
  UseComposerInteractionsArgs,
} from "./useComposerInteractions.types";

export function createComposerUploadHandlers(args: UseComposerInteractionsArgs): Pick<
  ComposerInteractionHandlers,
  "uploadDraftFiles" | "removeDraftAttachment"
> {
  const {
    uploadingAttachments,
    setUploadingAttachments,
    setError,
    selectedSessionId,
    setDraftAttachments,
    fileInputRef,
  } = args;

  const uploadDraftFiles = async (files: FileList | File[]) => {
    const normalizedFiles = Array.from(files);
    if (!normalizedFiles.length || uploadingAttachments) {
      return;
    }
    setUploadingAttachments(true);
    setError(null);
    try {
      const form = new FormData();
      normalizedFiles.forEach((file) => form.append("files", file));
      if (selectedSessionId) {
        form.append("session_id", selectedSessionId);
      }
      const response = await fetch("/chat/api/upload", {
        method: "POST",
        credentials: "same-origin",
        body: form,
      });
      if (!response.ok) {
        throw new Error("Failed to upload files");
      }
      const payload = (await response.json()) as {
        files: Array<{
          id: string;
          name: string;
          path: string;
          relativePath: string;
          mediaType: string;
          sizeBytes: number;
          url: string;
        }>;
      };
      setDraftAttachments((current) => [
        ...current,
        ...(payload.files || []).map((file) => ({
          ...file,
          id: `${file.path}:${file.sizeBytes}`,
        })),
      ]);
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : "Failed to upload files",
      );
    } finally {
      setUploadingAttachments(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const removeDraftAttachment = (attachmentId: string) => {
    setDraftAttachments((current) =>
      current.filter((attachment) => attachment.id !== attachmentId),
    );
  };

  return { uploadDraftFiles, removeDraftAttachment };
}
