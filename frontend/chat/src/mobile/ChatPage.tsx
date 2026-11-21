// One chat that runs on a Mac: the earlier messages, the current turn as it streams (text and tool lines), the
// approvals as cards, Stop while it runs, and the composer at the bottom. The turn is followed by polling the
// device jobs (every second while it runs): a phone's WebSocket does not survive the background.

import { useEffect } from "react";
import { jobState } from "../chat/devices/deviceJobsModel";
import { turnBlocks, turnView } from "../chat/devices/deviceTurnView";
import { stopJob } from "./mobileApi";
import { MarkdownRenderer } from "../chat/MarkdownRenderer";
import { codeChanges, claudeArtifacts, macFiles, serverArtifacts } from "./mobileFilesArtifacts";
import { compactions, contextUsage } from "./mobileUsageModel";
import { routeSuggestion } from "./mobileTurnOptions";
import { serverAnswerPending } from "./mobileDeviceChats";
import { Artifacts } from "./Artifacts";
import { MacFiles } from "./MacFiles";
import { ServerOptionsBar } from "./ServerOptionsBar";
import { TurnOptionsBar } from "./TurnOptionsBar";
import { Icon } from "./icons";
import { WriteApprovalCard } from "./WriteApprovalCard";
import { WritePlanApprovalCard } from "./WritePlanApprovalCard";
import { WorkflowProposalCard } from "./WorkflowProposalCard";
import { copy, theme } from "./mobileChatBrowser";
import { ChatPageHeader } from "./ChatPageHeader";
import { JobApprovals } from "./JobApprovals";
import { JobCodeChanges } from "./JobCodeChanges";
import { useChatPageState } from "./useChatPageState";
import { useChatPolling } from "./useChatPolling";
import { chatPageSubmit } from "./chatPageSubmit";

type Props = {
  sessionId: string;
  title: string;
  projectId: string;
  onBack: () => void;
  // A chat on the Server (no Mac): its model and thinking, answers polled from the messages.
  onServer?: boolean;
  // A taken-over Claude Code session; its messages go to the take-over endpoint, not the chat's send.
  localSessionId?: string;
  // Phase B: a fork of that session continues in its own thread (the take-over goes there, not to the original).
  forkThreadId?: string;
  // A workflow run this chat started (start card, "Open the run").
  onOpenRun?: (runId: string, title: string) => void;
};
type ChatPageState = ReturnType<typeof useChatPageState>;
type Job = ChatPageState["jobs"][number];

function renderMessages(messages: ChatPageState["messages"]) {
  return messages.map((message) =>
    message.role === "user" ? (
      <div key={message.id} className="m-user">
        {message.content}
      </div>
    ) : (
      <div key={message.id}>
        <div className="m-ai m-ai-md">
          <MarkdownRenderer content={message.content} theme={theme()} />
        </div>
        <button
          type="button"
          className="m-copy"
          onClick={() => copy(message.content)}
        >
          Copy
        </button>
      </div>
    ),
  );
}

function ChatCards({ page, sessionId, projectId, onOpenRun }: {
  page: ChatPageState;
  sessionId: string;
  projectId: string;
  onOpenRun?: (runId: string, title: string) => void;
}) {
  const { plans, plansDecidedHere, refresh, proposal, showProposal, writes } = page;
  return (
    <>
      {plans.map((plan) => (
        <WritePlanApprovalCard
          key={plan.id}
          plan={plan}
          onDecided={(id) => {
            plansDecidedHere.current.add(id);
            void refresh();
          }}
        />
      ))}
      {proposal && (
        <WorkflowProposalCard
          card={proposal}
          sessionId={sessionId}
          projectId={projectId}
          onAnswered={(raw) => {
            showProposal(raw);
            void refresh();
          }}
          onOpenRun={onOpenRun}
        />
      )}
      {writes.map((write) => (
        <WriteApprovalCard key={write.id} write={write} onDecided={() => void refresh()} />
      ))}
    </>
  );
}

function ChatCompose({ page, job, live, onServer, submit }: Omit<Parameters<typeof ChatDock>[0], "projectId">) {
  const { draft, setDraft, busy, refresh } = page;
  return (
    <footer className="m-compose">
      <textarea
        id="m-reply"
        aria-label="Reply"
        placeholder={
          job || onServer ? "Reply…" : "This chat has no Mac job"
        }
        rows={1}
        value={draft}
        disabled={!job && !onServer}
        onChange={(event) => setDraft(event.target.value)}
      />
      {live && job ? (
        <button
          type="button"
          className="m-stop"
          aria-label="Stop"
          onClick={() => void stopJob(job.id).then(refresh)}
        >
          <i />
        </button>
      ) : (
        <button
          type="button"
          className="m-send"
          aria-label="Send"
          disabled={!draft.trim() || busy || (!job && !onServer)}
          onClick={() => void submit()}
        >
          <Icon name="send" size={20} />
        </button>
      )}
    </footer>
  );
}

function ChatDock({ page, job, live, onServer, projectId, submit }: {
  page: ChatPageState;
  job: Job | null;
  live: boolean;
  onServer: boolean;
  projectId: string;
  submit: () => Promise<void>;
}) {
  const { serverOptions, setServerOptions, turnOptions, setTurnOptions } = page;
  return (
    <div className="m-dock">
      {onServer && (
        <ServerOptionsBar
          projectId={projectId}
          options={serverOptions}
          onChange={(patch) =>
            setServerOptions((current) => ({ ...current, ...patch }))
          }
        />
      )}
      {job && !job.profile.startsWith("local:") && (
        <TurnOptionsBar
          options={turnOptions}
          onChange={setTurnOptions}
          projectId={projectId}
          profile={job.profile === "seat" ? "seat" : "governed"}
          deviceId={job.deviceId}
        />
      )}
      <ChatCompose page={page} job={job} live={live} onServer={onServer} submit={submit} />
    </div>
  );
}

// What the page shows of the jobs and messages: the current job and its turn, code changes, files and pages.
function chatTurnFacts(
  jobs: ChatPageState["jobs"],
  rawMessages: ChatPageState["rawMessages"],
  messages: ChatPageState["messages"],
  onServer: boolean,
) {
  const job = jobs.length ? jobs[jobs.length - 1] : null;
  const changes = codeChanges(jobs.flatMap((item) => item.events));
  const files = macFiles(jobs);
  const claudePages = claudeArtifacts(jobs);
  const serverPages = serverArtifacts(rawMessages);
  const context = onServer ? null : contextUsage(jobs);
  const route = onServer ? null : routeSuggestion(jobs);
  const compacted = onServer ? { count: 0, freed: 0 } : compactions(jobs);
  const view = job ? turnView(job) : null;
  const state = job && view ? jobState(job, view.finished) : null;
  const live = !!state?.live;
  const waitingOnServer = onServer && serverAnswerPending(messages);
  return { job, changes, files, claudePages, serverPages, context, route, compacted, view, state, live, waitingOnServer };
}

function renderLiveTurn(view: NonNullable<ReturnType<typeof turnView>>) {
  return turnBlocks(view.items).map((block) =>
    block.kind === "text" ? (
      <div key={block.key} className="m-ai">
        {block.text}
      </div>
    ) : (
      <div key={block.key} className="m-tools">
        {block.tools.map((tool) => tool.tool).join(" · ")}
      </div>
    ),
  );
}

export function ChatPage({
  sessionId,
  title,
  projectId,
  onBack,
  onServer = false,
  localSessionId,
  forkThreadId,
  onOpenRun,
}: Props) {
  const page = useChatPageState(sessionId, onServer);
  const { messages, rawMessages, jobs, draft, setDraft, serverOptions, busy, setBusy, error, setError } = page;
  const { bottom, turnOptions, refresh } = page;

  const { job, changes, files, claudePages, serverPages, context, route, compacted, view, state, live, waitingOnServer } =
    chatTurnFacts(jobs, rawMessages, messages, onServer);

  useChatPolling(refresh, live, waitingOnServer, setError);

  useEffect(() => {
    // A block body: newer browsers return a promise from scrollIntoView, and an effect may only return a cleanup.
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length, view?.items.length, bottom]);

  const submit = chatPageSubmit({
    draft, setDraft, job, onServer, busy, setBusy, setError, localSessionId, forkThreadId, refresh, sessionId,
    projectId, serverOptions, turnOptions,
  });

  const pending = job?.approvals.filter((approval) => approval.status === "pending") ?? [];

  return (
    <div className="m-screen">
      <ChatPageHeader title={title} forkThreadId={forkThreadId} job={job} context={context} compacted={compacted}
        route={route} messages={messages} onBack={onBack} />
      <main className="m-body m-chat">
        {renderMessages(messages)}
        {view && live && renderLiveTurn(view)}
        <ChatCards page={page} sessionId={sessionId} projectId={projectId} onOpenRun={onOpenRun} />
        {job && <JobApprovals job={job} pending={pending} refresh={refresh} />}
        {state && (
          <p className={`m-state m-state-${state.tone}`}>{state.label}</p>
        )}
        {error && (
          <p className="m-error" role="alert">
            {error}
          </p>
        )}
        {changes.length > 0 && <JobCodeChanges changes={changes} />}
        <Artifacts claude={claudePages} server={serverPages} />
        <MacFiles files={files} />
        {onServer && serverAnswerPending(messages) && (
          <p className="m-state m-state-running">Working on the Server…</p>
        )}
        <div ref={bottom} />
      </main>
      <ChatDock page={page} job={job} live={live} onServer={onServer} projectId={projectId} submit={submit} />
    </div>
  );
}
