import { useCallback, useState, type Dispatch, type SetStateAction } from "react";

import { loadBoardMessages, loadBoardThread } from "./agentBoardApi";
import type { BoardFilters } from "./agentBoardApi";
import { BOARD_KINDS } from "./agentBoardTypes";
import { BOARD_PAGE_SIZE, BOARD_POLL_MS, boardLoadErrorText, mergeNewest, readBoardPage, readBoardThread, readViewer } from "./agentBoardModel";
import { KIND_LABEL, authorLabel } from "./agentBoardLabels";
import type { BoardMessage, BoardViewer, BoardWorkItem } from "./agentBoardTypes";
import { AgentsBoardMessage } from "./AgentsBoardMessage";
import { AgentsHandoffRequest } from "./AgentsHandoffRequest";
import { useVisiblePolling } from "./useVisiblePolling";

type Listing = { key: string; items: BoardMessage[]; nextCursor: string | null };
type Thread = { root: BoardMessage; replies: BoardMessage[] };
type Known = { workItems: Map<string, BoardWorkItem>; agents: Map<string, string> };
type Problem = { key: string; text: string } | null;

// Adds the work items and agents named by the messages to the filter choices.
function rememberMessages(previous: Known, items: BoardMessage[]): Known {
  const workItems = new Map(previous.workItems);
  const agents = new Map(previous.agents);
  for (const message of items) {
    if (message.workItem) workItems.set(message.workItem.id, message.workItem);
    if (message.agentHash && message.authorType === "agent") agents.set(message.agentHash, authorLabel(message));
  }
  return { workItems, agents };
}

type ListContext = {
  projectId: string;
  filters: BoardFilters;
  key: string;
  remember: (items: BoardMessage[]) => void;
  setProblem: (problem: Problem) => void;
  setViewer: (viewer: BoardViewer | null) => void;
  setListing: Dispatch<SetStateAction<Listing | null>>;
};

// Reads the newest page of the board and merges it into the listing of the same filters.
function fetchBoardList(ctx: ListContext, isCurrent: () => boolean) {
  const { projectId, filters, key, remember, setProblem, setViewer, setListing } = ctx;
  void loadBoardMessages(projectId, filters, null, BOARD_PAGE_SIZE).then((payload) => {
    if (!isCurrent()) return;
    const page = readBoardPage(payload);
    if (!page) {
      setProblem({ key, text: "The server's answer was not a list of board messages." });
      return;
    }
    setProblem(null);
    setViewer(readViewer(payload));
    remember(page.items);
    setListing((previous) => previous?.key === key
      ? { key, items: mergeNewest(page.items, previous.items), nextCursor: previous.nextCursor ?? page.nextCursor }
      : { key, items: page.items, nextCursor: page.nextCursor });
  }).catch((error) => {
    if (isCurrent()) setProblem({ key, text: boardLoadErrorText(error, "board messages") });
  });
}

// Reads the next older page of the listing, if there is one.
function fetchOlderMessages(ctx: Omit<ListContext, "setViewer">, listing: Listing | null) {
  const { projectId, filters, key, remember, setProblem, setListing } = ctx;
  const cursor = listing?.key === key ? listing.nextCursor : null;
  if (!cursor) return;
  void loadBoardMessages(projectId, filters, cursor, BOARD_PAGE_SIZE).then((payload) => {
    const page = readBoardPage(payload);
    if (!page) return;
    remember(page.items);
    setListing((previous) => previous?.key === key
      ? { key, items: mergeNewest(previous.items, page.items), nextCursor: page.nextCursor }
      : previous);
  }).catch((error) => setProblem({ key, text: boardLoadErrorText(error, "older board messages") }));
}

function fetchBoardThread(
  ctx: {
    remember: (items: BoardMessage[]) => void;
    setThread: (thread: Thread | null) => void;
    setThreadProblem: (problem: string | null) => void;
    setViewer: (viewer: BoardViewer | null) => void;
  },
  id: string,
  isCurrent: () => boolean,
) {
  const { remember, setThread, setThreadProblem, setViewer } = ctx;
  setThreadProblem(null);
  void loadBoardThread(id).then((payload) => {
    if (!isCurrent()) return;
    const read = readBoardThread(payload);
    setThread(read);
    setViewer(readViewer(payload));
    if (!read) setThreadProblem("The server's answer was not a readable thread.");
    else remember([read.root, ...read.replies]);
  }).catch((error) => {
    if (isCurrent()) { setThread(null); setThreadProblem(boardLoadErrorText(error, "thread")); }
  });
}

function BoardThreadView({ thread, threadProblem, card, onBack }: {
  thread: Thread | null;
  threadProblem: string | null;
  card: (message: BoardMessage, inThread: boolean) => JSX.Element;
  onBack: () => void;
}) {
  return (
    <section className="agents-board" aria-label="Thread" data-testid="agents-board-thread">
      <div className="agents-board__actions">
        <button type="button" className="admin-panel__action-btn" onClick={onBack}>Back to the board</button>
      </div>
      {threadProblem ? <p className="work-area__error" role="alert">{threadProblem}</p>
        : !thread ? <p className="agents-area__hint" role="status">Loading the thread…</p>
          : <>{card(thread.root, true)}<div className="agents-board__replies">{thread.replies.map((reply) => card(reply, true))}</div></>}
    </section>
  );
}

function BoardFilterBar({ filters, known, setFilter, showHandoff, openHandoff }: {
  filters: BoardFilters;
  known: Known;
  setFilter: (name: keyof BoardFilters, value: string) => void;
  showHandoff: boolean;
  openHandoff: () => void;
}) {
  return (
    <div className="agents-toolbar" role="group" aria-label="Filter messages">
      <label className="admin-panel__field"><span>Work item</span>
        <select value={filters.workItemId ?? ""} onChange={(event) => setFilter("workItemId", event.target.value)}>
          <option value="">All work items</option>
          {Array.from(known.workItems.values()).map((item) => <option key={item.id} value={item.id}>{item.key || item.title}</option>)}
        </select>
      </label>
      <label className="admin-panel__field"><span>Kind</span>
        <select value={filters.kind ?? ""} onChange={(event) => setFilter("kind", event.target.value)}>
          <option value="">All kinds</option>
          {BOARD_KINDS.map((kind) => <option key={kind} value={kind}>{KIND_LABEL[kind]}</option>)}
        </select>
      </label>
      <label className="admin-panel__field"><span>Agent</span>
        <select value={filters.agentHash ?? ""} onChange={(event) => setFilter("agentHash", event.target.value)}>
          <option value="">All agents</option>
          {Array.from(known.agents).map(([hash, label]) => <option key={hash} value={hash}>{label}</option>)}
        </select>
      </label>
      {showHandoff ? (
        <button type="button" className="admin-panel__action-btn agents-toolbar__end" onClick={openHandoff}>Request handoff to…</button>
      ) : null}
    </div>
  );
}

// The messages of the current filters, or the refusal, the loading line or the empty line, then "Load older".
function BoardListing({ problem, items, hasOlder, card, loadOlder }: {
  problem: Problem;
  items: BoardMessage[] | null;
  hasOlder: boolean;
  card: (message: BoardMessage, inThread: boolean) => JSX.Element;
  loadOlder: () => void;
}) {
  return (
    <>
      {problem ? <p className="work-area__error" role="alert" data-testid="agents-board-error">{problem.text}</p>
        : items === null ? <p className="agents-area__hint" role="status">Loading the board…</p>
          : !items.length ? <p className="admin-panel__empty-state" data-testid="agents-board-empty">No agent message here yet.</p>
            : items.map((message) => card(message, false))}
      {items?.length && hasOlder ? (
        <div className="agents-board__actions">
          <button type="button" className="admin-panel__action-btn" onClick={loadOlder}>Load older messages</button>
        </div>
      ) : null}
    </>
  );
}

// The "Message board" view: every agent message of the Workspace, newest first, filterable by
// work item, kind and agent, with a thread view. Polls every 10 s while visible and at once when the tab comes back.
// Read-only for agents' content; the only human actions are answering a decision request and the admin actions. Who
// may do what is offered from the latest answer's `viewer` (D-F1); the server authorizes every action.
export function AgentsMessageBoard({ projectId, isPlatformAdmin = false, focusMessageId = null, pollMs = BOARD_POLL_MS }: {
  projectId: string;
  // The platform-admin role of the signed-in user (judge-board L7): such a user may decide every request.
  isPlatformAdmin?: boolean;
  focusMessageId?: string | null;
  pollMs?: number;
}) {
  const [filters, setFilters] = useState<BoardFilters>({});
  const [listing, setListing] = useState<Listing | null>(null);
  const [problem, setProblem] = useState<{ key: string; text: string } | null>(null);
  const [known, setKnown] = useState<Known>(() => ({ workItems: new Map(), agents: new Map() }));
  const [threadId, setThreadId] = useState<string | null>(focusMessageId);
  const [thread, setThread] = useState<Thread | null>(null);
  const [threadProblem, setThreadProblem] = useState<string | null>(null);
  const [handoffOpen, setHandoffOpen] = useState(false);
  const [viewer, setViewer] = useState<BoardViewer | null>(null);
  const isAdmin = viewer?.canAdmin === true;
  const key = `${projectId}|${filters.workItemId ?? ""}|${filters.kind ?? ""}|${filters.agentHash ?? ""}`;
  const remember = useCallback((items: BoardMessage[]) => setKnown((previous) => rememberMessages(previous, items)), []);

  const loadList = useCallback((isCurrent: () => boolean) => {
    fetchBoardList({ projectId, filters, key, remember, setProblem, setViewer, setListing }, isCurrent);
  }, [projectId, filters, key, remember]);

  const loadThread = useCallback((id: string, isCurrent: () => boolean = () => true) => {
    fetchBoardThread({ remember, setThread, setThreadProblem, setViewer }, id, isCurrent);
  }, [remember]);

  useVisiblePolling(loadList, threadId ? null : key, pollMs);
  useVisiblePolling((isCurrent) => { if (threadId) loadThread(threadId, isCurrent); }, threadId ? `thread|${threadId}` : null, pollMs);
  const loadOlder = () => fetchOlderMessages({ projectId, filters, key, remember, setProblem, setListing }, listing);

  const items = listing?.key === key ? listing.items : null;
  const refresh = () => { if (threadId) loadThread(threadId); else loadList(() => true); };
  const card = (message: BoardMessage, inThread: boolean) => (
    <AgentsBoardMessage key={message.id} message={message} projectId={projectId} viewer={viewer} isPlatformAdmin={isPlatformAdmin}
      focused={message.id === focusMessageId} onOpenThread={inThread ? undefined : setThreadId} onChanged={refresh} />
  );
  const setFilter = (name: keyof BoardFilters, value: string) => setFilters((previous) => ({ ...previous, [name]: value || undefined }));

  if (threadId) {
    return <BoardThreadView thread={thread} threadProblem={threadProblem} card={card}
      onBack={() => { setThreadId(null); setThread(null); }} />;
  }

  return (
    <section className="agents-board" aria-label="Message board" data-testid="agents-board">
      <BoardFilterBar filters={filters} known={known} setFilter={setFilter} showHandoff={isAdmin && !handoffOpen}
        openHandoff={() => setHandoffOpen(true)} />
      {handoffOpen ? (
        <AgentsHandoffRequest projectId={projectId} workItems={Array.from(known.workItems.values())}
          onPosted={() => loadList(() => true)} onClose={() => setHandoffOpen(false)} />
      ) : null}
      <p className="agents-area__hint">Humans steer agents through chat and their own agent, not through the board.</p>
      <BoardListing problem={problem?.key === key ? problem : null} items={items} hasOlder={Boolean(listing?.nextCursor)}
        card={card} loadOlder={loadOlder} />
    </section>
  );
}
