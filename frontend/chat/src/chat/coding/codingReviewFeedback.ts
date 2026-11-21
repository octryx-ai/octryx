// The workspace state hook, the selected file's review view (its events, editor content, human edit) and the save of one feedback event.
import { useEffect, useMemo, useState } from "react";

import { createCodingReviewEvent } from "../work/workCodingApi";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkChangeUnit } from "../work/workPullRequestTypes";
import type { WorkCodingReviewEvent } from "../work/workCodingReviewTypes";
import type { CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import { DEFAULT_FORM, buildEditorContent, fileCandidates, type ReviewFormState } from "./codingReviewWorkspaceModel";

// The workspace's events, file choice and form; the first planned file is picked once the files are known.
export function useReviewWorkspaceState(
  session: CodingSessionSummary,
  detail: CodingSessionDetailData | null,
  latestPlan: WorkChangePlan | null,
) {
  const [events, setEvents] = useState<WorkCodingReviewEvent[]>(detail?.reviewEventsPayload?.items || []);
  const [selectedFile, setSelectedFile] = useState("");
  const [form, setForm] = useState<ReviewFormState>(DEFAULT_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const files = useMemo(() => fileCandidates(session, detail?.changeUnits || [], latestPlan), [session, detail, latestPlan]);

  useEffect(() => {
    setEvents(detail?.reviewEventsPayload?.items || []);
  }, [detail?.reviewEventsPayload?.items]);

  useEffect(() => {
    if (!selectedFile && files.length > 0) {
      setSelectedFile(files[0]);
    }
  }, [files, selectedFile]);

  return { events, setEvents, selectedFile, setSelectedFile, form, setForm, saving, setSaving, error, setError, files };
}

export function reviewFileView(
  session: CodingSessionSummary,
  changeUnits: WorkChangeUnit[],
  events: WorkCodingReviewEvent[],
  selectedFile: string,
  form: ReviewFormState,
) {
  const selectedChangeUnit = changeUnits.find((unit) => unit.expected_paths.includes(selectedFile));
  const fileEvents = events.filter((event) => event.file_path === selectedFile);
  const editorContent = buildEditorContent({
    session,
    selectedFile,
    selectedChangeUnit,
    fileEvents,
  });
  const latestHumanEdit = [...fileEvents].reverse().find((event) => event.event_type === "manual_edit" && event.updated_content);
  const modifiedContent = form.eventType === "manual_edit" && form.updatedContent
    ? form.updatedContent
    : latestHumanEdit?.updated_content || editorContent;
  const canSave = Boolean(selectedFile && form.body.trim() && (form.eventType !== "manual_edit" || form.updatedContent.trim()));
  return { selectedChangeUnit, fileEvents, editorContent, latestHumanEdit, modifiedContent, canSave };
}

type SaveInput = {
  sessionId: string;
  selectedFile: string;
  changeUnitId: string | null;
  editorContent: string;
  form: ReviewFormState;
};

export function saveReviewFeedback({ sessionId, selectedFile, changeUnitId, editorContent, form }: SaveInput) {
  return createCodingReviewEvent(sessionId, {
    change_unit_id: changeUnitId,
    event_type: form.eventType,
    file_path: selectedFile,
    line_number: Number.parseInt(form.lineNumber, 10) || null,
    severity: form.severity,
    body: form.body.trim(),
    original_content: editorContent,
    updated_content: form.eventType === "manual_edit" ? form.updatedContent : null,
    metadata: { source: "coding_review_workspace" },
    agent_context: {
      source: "human_review",
      constraint:
        form.eventType === "manual_edit"
          ? `Preserve the human edit for ${selectedFile}.`
          : "Resolve reviewer feedback before implementation closeout.",
    },
  });
}
