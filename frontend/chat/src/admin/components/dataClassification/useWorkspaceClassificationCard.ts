// The Workspace classification card's state: the classification, the seat switches, the Codex engines and models,
// loaded together for one Workspace, and the saves that reload it.
import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { loadWorkspaceEngines } from "../../../chat/engines/engineApi";
import { readWorkspaceEngines } from "../../../chat/engines/engineModel";
import { codexSeatBody, codexSeatSavedText, readCodexSeat } from "./codexSeatModel";
import type { CodexSeat } from "./codexSeatModel";
import { readSeatInEffect, readSeatSet } from "./seatStateModel";
import { loadSeatMode, loadWorkspaceClassification, saveCodexSeatMode, saveSeatMode, saveWorkspaceClassification } from "./dataClassificationApi";
import { CLEAR_HINT, classificationLoadErrorText, classificationSaveErrorText, readSeatMode, readWorkspaceClassification } from "./dataClassificationModel";
import type { SeatMode, WorkspaceClassification } from "./dataClassificationTypes";
import { readCodexSeatModels } from "./codexSeatModelsModel";
import type { CodexModelsView } from "./codexSeatModelsModel";
import { readSeatPolicySettings } from "./seatPolicyModel";
import type { SeatPolicySettings as SeatSettings } from "./seatPolicyModel";

export type CardMessage = { ok: boolean; text: string };
type Setter<T> = Dispatch<SetStateAction<T>>;
type SeatSet = { claude: boolean | null; codex: boolean | null };

type CardSetters = {
  setModel: Setter<WorkspaceClassification | null>; setDraft: Setter<string>; setProblem: Setter<string | null>;
  setSeatMode: Setter<SeatMode | null>; setSeatInEffect: Setter<boolean | null>; setSeatSet: Setter<SeatSet>;
  setCodex: Setter<CodexSeat>; setSeatSettings: Setter<SeatSettings>; setCodexModels: Setter<CodexModelsView>;
  setCodexEngines: Setter<string[] | null>;
};

async function loadClassification(projectId: string, isCurrent: () => boolean, s: CardSetters) {
  try {
    const read = readWorkspaceClassification(await loadWorkspaceClassification(projectId));
    if (!isCurrent()) return;
    s.setModel(read);
    s.setDraft(read?.effective ?? "");
    s.setProblem(read ? null : "The server's answer listed no classification levels.");
  } catch (error) {
    if (!isCurrent()) return;
    s.setModel(null);
    s.setProblem(classificationLoadErrorText(error));
  }
}

async function loadSeats(projectId: string, isCurrent: () => boolean, s: CardSetters) {
  try {
    const answer = await loadSeatMode(projectId);
    if (isCurrent()) { s.setSeatMode(readSeatMode(answer)); s.setSeatInEffect(readSeatInEffect(answer)); s.setSeatSet({ claude: readSeatSet(answer, "seat_mode_set"), codex: readSeatSet(answer, "codex_seat_mode_set") }); s.setCodex(readCodexSeat(answer)); s.setSeatSettings(readSeatPolicySettings(answer)); s.setCodexModels(readCodexSeatModels(answer)); }
  } catch {
    if (isCurrent()) { s.setSeatMode(null); s.setSeatInEffect(null); s.setSeatSet({ claude: null, codex: null }); s.setCodex({ mode: null, inEffect: null, reason: null }); s.setSeatSettings(readSeatPolicySettings(null)); s.setCodexModels({ kind: "unknown" }); }
  }
}

async function loadCodexEngines(projectId: string, isCurrent: () => boolean, s: CardSetters) {
  try {
    const engines = readWorkspaceEngines(await loadWorkspaceEngines(projectId));
    if (isCurrent()) s.setCodexEngines(engines ? engines.effective.allowed : null);
  } catch {
    if (isCurrent()) s.setCodexEngines(null);
  }
}

async function loadCard(projectId: string, isCurrent: () => boolean, s: CardSetters) {
  await loadClassification(projectId, isCurrent, s);
  await loadSeats(projectId, isCurrent, s);
  await loadCodexEngines(projectId, isCurrent, s);
}

// One save: busy while it runs, then reload and say how it went.
async function savingStep(
  setSaving: Setter<boolean>, setMessage: Setter<CardMessage | null>, load: () => Promise<void>,
  run: () => Promise<unknown>, okText: string, failText: (error: unknown) => string,
) {
  setSaving(true);
  setMessage(null);
  try {
    await run();
    await load();
    setMessage({ ok: true, text: okText });
  } catch (error) {
    setMessage({ ok: false, text: failText(error) });
  } finally {
    setSaving(false);
  }
}

export function useWorkspaceClassificationCard(projectId: string) {
  const [model, setModel] = useState<WorkspaceClassification | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [seatMode, setSeatMode] = useState<SeatMode | null>(null);
  const [seatInEffect, setSeatInEffect] = useState<boolean | null>(null);
  const [seatSet, setSeatSet] = useState<SeatSet>({ claude: null, codex: null });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<CardMessage | null>(null);
  const [seatMessage, setSeatMessage] = useState<CardMessage | null>(null);
  const [codex, setCodex] = useState<CodexSeat>({ mode: null, inEffect: null, reason: null });
  const [codexEngines, setCodexEngines] = useState<string[] | null>(null);
  const [codexMessage, setCodexMessage] = useState<CardMessage | null>(null);
  const [seatSettings, setSeatSettings] = useState<SeatSettings>(() => readSeatPolicySettings(null));
  const [codexModels, setCodexModels] = useState<CodexModelsView>({ kind: "unknown" });

  const load = useCallback(async (isCurrent: () => boolean = () => true) => {
    await loadCard(projectId, isCurrent, {
      setModel, setDraft, setProblem, setSeatMode, setSeatInEffect, setSeatSet, setCodex, setSeatSettings, setCodexModels,
      setCodexEngines,
    });
  }, [projectId]);

  useEffect(() => {
    let current = true;
    setModel(null);
    setProblem(null);
    setMessage(null);
    setSeatMessage(null);
    setCodexMessage(null);
    void load(() => current);
    return () => { current = false; };
  }, [load]);

  const save = () => savingStep(setSaving, setMessage, load, () => saveWorkspaceClassification(projectId, draft || null),
    draft ? "Saved for this Workspace." : `Saved: not set. ${CLEAR_HINT}`, (error) => classificationSaveErrorText(error));
  const toggleSeat = (allowed: boolean) => savingStep(setSaving, setSeatMessage, load,
    () => saveSeatMode(projectId, allowed ? "allowed" : "forbidden"),
    allowed ? "Seat sessions are allowed here." : "Seat sessions are no longer allowed here.",
    (error) => classificationSaveErrorText(error, "the seat setting"));
  const toggleCodex = (allowed: boolean) => savingStep(setSaving, setCodexMessage, load,
    () => saveCodexSeatMode(projectId, codexSeatBody(allowed)), codexSeatSavedText(allowed),
    (error) => classificationSaveErrorText(error, "the Codex seat setting"));
  return {
    model, problem, draft, setDraft, seatMode, seatInEffect, seatSet, saving, message, setMessage, seatMessage, codex,
    codexEngines, codexMessage, seatSettings, codexModels, load, save, toggleSeat, toggleCodex,
  };
}
