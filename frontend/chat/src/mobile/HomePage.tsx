// Home: what needs the person first, then the state of their work at a glance (tiles that open the tabs), the tasks
// assigned to them and the newest chats. Everything follows the Workspace choice.

import { useState, type ReactNode } from "react";
import type { AttentionItem } from "../chat/companion/companionTypes";
import { RedactedText } from "../chat/redaction/RedactedText";
import { ChatRows } from "./ChatList";
import { Icon } from "./icons";
import type { Case } from "./mobileTasksModel";
import type { DeviceThread } from "./mobileDeviceChats";
import type { TerminalSession } from "./mobileTerminalSessions";
import type { Usage } from "./mobileUsageModel";
import { shortTime, usageText } from "./mobileUsageModel";
import { approvalMeta, type PhoneApproval } from "./phoneApprovals";
import { TabHeader } from "./PageHeader";
import { requestRefresh } from "./pullToRefresh";
import { TaskRow } from "./TaskRow";

export type HomeTile = { key: string; label: string; value: number | string; hint: string; tone?: "attention"; onOpen: () => void };

type Props = {
  switcher: ReactNode;
  needs: AttentionItem[];
  // Approvals this person may decide; the needs above do not repeat them.
  approvals: PhoneApproval[];
  tiles: HomeTile[];
  threads: DeviceThread[];
  sessions: TerminalSession[];
  cases: Case[];
  workspaces: Record<string, string>;
  usage: Usage | null;
  loading: boolean;
  error: string;
  onOpenItem: (item: AttentionItem) => void;
  onTakeOver: (item: AttentionItem) => Promise<void>;
  onOpenApproval: (approval: PhoneApproval) => void;
  onOpenCase: (item: Case) => void;
  onOpenThread: (thread: DeviceThread) => void;
  onOpenSession: (session: TerminalSession) => void;
  onAllChats: () => void;
  onNewChat: () => void;
};

const RECENT_CHATS = 4;
const YOUR_TASKS = 3;

export function HomePage({
  switcher, needs, approvals, tiles, threads, sessions, cases, workspaces, usage, loading, error, onOpenItem, onTakeOver, onOpenApproval,
  onOpenCase, onOpenThread, onOpenSession, onAllChats, onNewChat,
}: Props) {
  const usageLine = usage ? usageText(usage) : "";
  const hasChats = threads.length + sessions.length > 0;
  return (
    <>
      <TabHeader
        title="Home"
        switcher={switcher}
        subtitle={usageLine ? <span className={usage?.warn ? "m-warn" : undefined}>{usageLine}</span> : undefined}
        actions={<HomeActions loading={loading} onNewChat={onNewChat} />}
      />
      <main className="m-body">
        {error && (
          <p className="m-banner m-banner-problem" role="alert">
            {error}
          </p>
        )}
        {needs.length + approvals.length > 0 && (
          <NeedsSection needs={needs} approvals={approvals} workspaces={workspaces} onOpenItem={onOpenItem} onTakeOver={onTakeOver}
            onOpenApproval={onOpenApproval} />
        )}
        {tiles.length > 0 && <TilesSection tiles={tiles} />}
        {cases.length > 0 && <TasksSection cases={cases} workspaces={workspaces} onOpenCase={onOpenCase} />}
        <section aria-labelledby="m-recent">
          <div className="m-section-row">
            <h2 id="m-recent" className="m-section">
              Recent chats
            </h2>
            {hasChats && (
              <button type="button" className="m-text-button" onClick={onAllChats}>
                All chats
              </button>
            )}
          </div>
          {loading && !hasChats && <p className="m-empty">Loading…</p>}
          {!loading && !hasChats && (
            <div className="m-empty">
              <p>No chats here yet.</p>
              <button type="button" className="m-secondary" onClick={onNewChat}>
                Start a chat
              </button>
            </div>
          )}
          <ChatRows
            threads={threads}
            sessions={sessions}
            limit={RECENT_CHATS}
            onOpenThread={onOpenThread}
            onOpenSession={onOpenSession}
          />
        </section>
      </main>
    </>
  );
}

function HomeActions({ loading, onNewChat }: Pick<Props, "loading" | "onNewChat">) {
  return (
    <>
      <button
        type="button"
        className={`m-icon-button${loading ? " m-spin" : ""}`}
        aria-label="Refresh"
        onClick={() => void requestRefresh()}
      >
        <Icon name="refresh" size={22} />
      </button>
      <button type="button" className="m-pill-button" onClick={onNewChat}>
        <Icon name="plus" size={18} />
        New chat
      </button>
    </>
  );
}

// Approvals first, then the other items that need the person.
function NeedsSection({ needs, approvals, workspaces, onOpenItem, onTakeOver, onOpenApproval }:
  Pick<Props, "needs" | "approvals" | "workspaces" | "onOpenItem" | "onTakeOver" | "onOpenApproval">) {
  return (
    <section aria-labelledby="m-needs">
      <h2 id="m-needs" className="m-section">
        Needs you <span className="m-count">{needs.length + approvals.length}</span>
      </h2>
      <ul className="m-cards">
        {approvals.map((approval) => (
          <li key={`approval:${approval.id}`}>
            <button
              type="button"
              className="m-need"
              data-testid="m-approval-row"
              onClick={() => onOpenApproval(approval)}
            >
              <span className="m-need-text">
                <b><RedactedText value={approval.title} /></b>
                <span>
                  {[
                    "Approval",
                    approvalMeta({
                      workspace: approval.workspaceId ? workspaces[approval.workspaceId] ?? "" : "",
                      requestedBy: approval.requestedByName ?? "",
                      ago: shortTime(approval.createdAt),
                    }),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              <Icon name="chevronRight" size={18} className="m-row-chevron" />
            </button>
          </li>
        ))}
        {needs.map((item) => <NeedRow key={item.key} item={item} onOpenItem={onOpenItem} onTakeOver={onTakeOver} />)}
      </ul>
    </section>
  );
}

// A session handed to the person or waiting in the pool is taken over right here; the server's refusal (someone was
// faster, no device can run it) is shown in its own words.
function NeedRow({ item, onOpenItem, onTakeOver }: { item: AttentionItem } & Pick<Props, "onOpenItem" | "onTakeOver">) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const takes = item.kind === "pool" || item.kind === "handover";
  const take = () => {
    setBusy(true);
    setProblem("");
    onTakeOver(item).catch((error: { message?: string }) => setProblem(error?.message || "It could not be taken over."))
      .finally(() => setBusy(false));
  };
  return (
    <li>
      <button type="button" className="m-need" onClick={() => onOpenItem(item)}>
        <span className="m-need-text">
          <b>{item.title}</b>
          <span>{[item.subtitle, item.workspace?.name].filter(Boolean).join(" · ")}</span>
        </span>
        <Icon name="chevronRight" size={18} className="m-row-chevron" />
      </button>
      {takes && (
        <div className="m-buttons">
          <button type="button" className="m-primary m-wide" disabled={busy} data-testid="m-take-over" onClick={take}>
            {busy ? "Taking over…" : "Take over"}
          </button>
        </div>
      )}
      {problem && <p className="m-error" role="alert">{problem}</p>}
    </li>
  );
}

function TilesSection({ tiles }: Pick<Props, "tiles">) {
  return (
    <section aria-label="Overview">
      <ul className="m-tiles">
        {tiles.map((tile) => (
          <li key={tile.key}>
            <button type="button" className="m-tile" onClick={tile.onOpen}>
              <span className="m-tile-label">{tile.label}</span>
              <span className={`m-tile-value${tile.tone ? ` m-tile-${tile.tone}` : ""}`}>{tile.value}</span>
              <span className="m-tile-hint">{tile.hint}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function TasksSection({ cases, workspaces, onOpenCase }: Pick<Props, "cases" | "workspaces" | "onOpenCase">) {
  return (
    <section aria-labelledby="m-yours">
      <h2 id="m-yours" className="m-section">
        Assigned to you <span className="m-count">{cases.length}</span>
      </h2>
      <ul className="m-rows m-group">
        {cases.slice(0, YOUR_TASKS).map((item) => (
          <TaskRow key={item.id} item={item} workspace={workspaces[item.projectId] ?? ""} onOpen={onOpenCase} />
        ))}
      </ul>
    </section>
  );
}
