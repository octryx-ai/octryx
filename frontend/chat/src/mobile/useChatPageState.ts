// The mobile chat's data: messages and Mac jobs polled from the server, pending writes, plans and the proposal.

import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import { readJobs } from "../chat/devices/deviceJobsModel";
import { type DeviceJob } from "../chat/devices/deviceJobTypes";
import { loadJobs, loadMessages, loadSessionView } from "./mobileApi";
import { knownSeqs, mergeJobs, partialJobIds, serverAnswerPending } from "./mobileDeviceChats";
import { useRefreshEvent } from "./pullToRefresh";
import type { ServerOptions } from "./ServerOptionsBar";
import { useTurnOptions } from "./useTurnOptions";
import { pendingWrites, type PendingWrite } from "./WriteApprovalCard";
import { pendingWritePlans, type PendingPlan } from "./WritePlanApprovalCard";
import { phoneProposal, proposalStillOpen, type PhoneProposal } from "./workflowProposalPhone";
import { selecting } from "./mobileChatBrowser";
import { readMessages, type Message } from "./chatPageMessages";

export function useChatPageState(sessionId: string, onServer: boolean) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [rawMessages, setRawMessages] = useState<unknown[]>([]);
  const [jobs, setJobs] = useState<DeviceJob[]>([]);
  // The jobs with every event the phone already has (the next poll asks only for newer ones).
  const jobsSeen = useRef<DeviceJob[]>([]);
  useEffect(() => {
    jobsSeen.current = []; // another chat: nothing it may continue from
  }, [sessionId]);
  const [draft, setDraft] = useState("");
  const [serverOptions, setServerOptions] = useState<ServerOptions>({
    runtimeTargetId: "",
    thinkingLevel: "light",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // A Server chat's connector writes waiting for the person; read with the chat's state.
  const [writes, setWrites] = useState<PendingWrite[]>([]);
  // The chat's write plan; a plan decided here stays as its one-line result.
  const [plans, setPlans] = useState<PendingPlan[]>([]);
  const plansDecidedHere = useRef(new Set<string>());
  // The chat's held workflow proposal: the start card or the plain prompt, read with the chat's state.
  const [proposal, setProposal] = useState<PhoneProposal | null>(null);
  const proposalOpen = useRef(false);
  const showProposal = useCallback((raw: Parameters<typeof phoneProposal>[0]) => {
    const card = phoneProposal(raw);
    proposalOpen.current = proposalStillOpen(card);
    setProposal(card);
  }, []);
  const viewAsked = useRef(false);
  const bottom = useRef<HTMLDivElement | null>(null);

  const [turnOptions, setTurnOptions] = useTurnOptions(sessionId);
  const writesOpen = useRef(false);
  const refresh = useChatRefresh({
    sessionId, onServer, jobsSeen, viewAsked, writesOpen, proposalOpen, plansDecidedHere, showProposal,
    setMessages, setRawMessages, setJobs, setWrites, setPlans,
  });
  return {
    messages, rawMessages, jobs, draft, setDraft, serverOptions, setServerOptions, busy, setBusy, error, setError,
    writes, plans, plansDecidedHere, proposal, showProposal, bottom, turnOptions, setTurnOptions, refresh,
  };
}

// Reads the chat's messages and new job events; a Server chat also reads its pending writes, plan and proposal.
function useChatRefresh({ sessionId, onServer, jobsSeen, viewAsked, writesOpen, proposalOpen, plansDecidedHere,
  showProposal, setMessages, setRawMessages, setJobs, setWrites, setPlans }: {
  sessionId: string;
  onServer: boolean;
  jobsSeen: MutableRefObject<DeviceJob[]>;
  viewAsked: MutableRefObject<boolean>;
  writesOpen: MutableRefObject<boolean>;
  proposalOpen: MutableRefObject<boolean>;
  plansDecidedHere: MutableRefObject<Set<string>>;
  showProposal: (raw: Parameters<typeof phoneProposal>[0]) => void;
  setMessages: (messages: Message[]) => void;
  setRawMessages: (messages: unknown[]) => void;
  setJobs: (jobs: DeviceJob[]) => void;
  setWrites: (writes: PendingWrite[]) => void;
  setPlans: (plans: PendingPlan[]) => void;
}) {
  const refresh = useCallback(async () => {
    if (selecting()) return;
    const [page, raw] = await Promise.all([
      loadMessages(sessionId),
      onServer ? Promise.resolve({ items: [] }) : loadJobs(sessionId, knownSeqs(jobsSeen.current)),
    ]);
    const read = readMessages(page.messages ?? []);
    // The chat's state is larger than its messages: asked once, then while an answer or a write is pending.
    if (onServer && (!viewAsked.current || serverAnswerPending(read) || writesOpen.current || proposalOpen.current)) {
      viewAsked.current = true;
      const state = await loadSessionView(sessionId).catch(() => null);
      if (state) {
        const next = pendingWrites(state.selectedApprovals);
        const nextPlans = pendingWritePlans(
          state.selectedApprovals,
          plansDecidedHere.current,
          typeof state.currentUser?.id === "string" ? state.currentUser.id : null,
        );
        writesOpen.current = next.length > 0 || nextPlans.some((plan) => !plan.decided);
        setWrites(next);
        setPlans(nextPlans);
        showProposal(state.selectedSession?.workflowProposal);
      }
    }
    setMessages(read);
    setRawMessages(page.messages ?? []);
    // Only new events come for the jobs the phone already has; they join the ones it kept.
    const next = mergeJobs(jobsSeen.current, readJobs(raw) ?? [], partialJobIds(raw));
    jobsSeen.current = next;
    setJobs(next);
  }, [sessionId, onServer, showProposal, jobsSeen, plansDecidedHere, proposalOpen, setJobs, setMessages, setPlans,
    setRawMessages, setWrites, viewAsked, writesOpen]);

  useRefreshEvent(refresh);
  return refresh;
}
