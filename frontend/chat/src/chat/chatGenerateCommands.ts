// The composer's generate commands: a task or a workflow draft made from the current chat.
import type { Dispatch, SetStateAction } from "react";

import type { SelectedSession } from "../chatThreadTypes";
import { readJson } from "./chatApiClient";

export type GenerateTaskResult = {
  taskName: string;
  taskUrl: string;
} | null;

export function isGenerateCommand(prompt: string) {
  return prompt === "/generate-task-from-chat" || prompt === "/generate-workflow";
}

type GenerateContext = {
  selectedSession: SelectedSession | null;
  setSending: Dispatch<SetStateAction<boolean>>;
  setComposerValue: Dispatch<SetStateAction<string>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setGenerateTaskResult: Dispatch<SetStateAction<GenerateTaskResult>>;
};

async function generateTaskFromChat(context: GenerateContext) {
  const { selectedSession, setSending, setComposerValue, setError, setGenerateTaskResult } = context;
  if (!selectedSession) {
    setError("No active session — start a conversation first");
    return;
  }
  setSending(true);
  setComposerValue("");
  setError(null);
  setGenerateTaskResult(null);
  try {
    const result = await readJson<{
      task_id: string;
      task_name: string;
      task_url: string;
    }>(`/chat/api/sessions/${selectedSession.id}/generate-task`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setGenerateTaskResult({
      taskName: result.task_name,
      taskUrl: result.task_url,
    });
  } catch (genError) {
    setError(
      genError instanceof Error
        ? genError.message
        : "Failed to generate task",
    );
  } finally {
    setSending(false);
  }
}

async function generateWorkflowDraft(context: GenerateContext) {
  const { selectedSession, setSending, setComposerValue, setError, setGenerateTaskResult } = context;
  if (!selectedSession) {
    setError("No active session — start a conversation first");
    return;
  }
  setSending(true);
  setComposerValue("");
  setError(null);
  setGenerateTaskResult(null);
  try {
    const result = await readJson<{
      flow: { id: string; name: string };
    }>(`/api/v1/flows/generate-from-session/${selectedSession.id}`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    setGenerateTaskResult({
      taskName: result.flow.name,
      taskUrl: "/chat",
    });
  } catch (genError) {
    setError(
      genError instanceof Error
        ? genError.message
        : "Failed to generate workflow draft",
    );
  } finally {
    setSending(false);
  }
}

export async function runGenerateCommand(prompt: string, context: GenerateContext) {
  if (prompt === "/generate-task-from-chat") {
    await generateTaskFromChat(context);
    return;
  }
  if (prompt === "/generate-workflow") {
    await generateWorkflowDraft(context);
  }
}
