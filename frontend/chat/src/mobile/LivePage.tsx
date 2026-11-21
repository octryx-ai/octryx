// A Claude Code session running on one of the person's Macs right now: the person writes
// to it the way another session would, through its inbox; the session keeps running in its terminal and answers
// back here. Nothing is taken over: the session decides what to do with the message, in its own permission mode.
import { forkLive, type ForkStarted } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { MAX_PICTURES } from "./pictures";
import { progressSteps, groupSteps } from "./mobileLiveProgress";
import { type LiveSession } from "./mobileLiveSessions";
import { Icon } from "./icons";
import { runLine } from "./engineSeatModel";
import { RunLineSubline } from "./RunLine";
import { FORK_REFUSALS, forkBlocked, forkReason } from "./liveSessionText";
import { copy } from "./mobileChatBrowser";
import { buildLiveTimeline } from "./liveTimeline";
import { Step, ToolGroup } from "./LiveSteps";
import { renderLiveMessage } from "./liveMessageView";
import { useLiveSession } from "./useLiveSession";
import { useFollowBottom } from "./useFollowBottom";
import { liveComposeActions } from "./liveComposeActions";

const STEPS_SHOWN = 40;
type LiveState = ReturnType<typeof useLiveSession>;

function LiveHeader({ session, status, messages, onBack }: {
  session: LiveSession;
  status: string;
  messages: LiveState["messages"];
  onBack: () => void;
}) {
  return (
  <header className="m-top">
    <button
      type="button"
      className="m-icon-button"
      aria-label="Back"
      onClick={onBack}
    >
      <Icon name="back" />
    </button>
    <div className="m-top-text">
      <strong>{session.name}</strong>
      {/* Engine and route as in the device chat; a live session reports no model. */}
      <RunLineSubline line={runLine(session)} more={[status, session.deviceName, session.folderName]} />
    </div>
    {messages.length > 0 && (
      <button
        type="button"
        className="m-icon-button"
        aria-label="Copy the whole conversation"
        onClick={() =>
          copy(
            messages
              .map(
                (message) =>
                  `${message.direction === "out" ? "You" : message.name || session.name}: ${message.text}`,
              )
              .join("\n\n"),
          )
        }
      >
        <Icon name="copy" size={20} />
      </button>
    )}
  </header>
  );
}

function LiveTimeline({ live, timeline, hiddenBlocks, stepCount }: {
  live: LiveState;
  timeline: ReturnType<typeof buildLiveTimeline>;
  hiddenBlocks: number;
  stepCount: number;
}) {
  const { messages, setAllSteps, openKeys, toggle, error, end } = live;
  return (
  <main className="m-body m-chat">
    {hiddenBlocks > 0 && (
      <button
        type="button"
        className="m-copy m-steps-more"
        onClick={() => setAllSteps(true)}
      >
        Show {hiddenBlocks} earlier steps
      </button>
    )}
    {messages.length === 0 && stepCount === 0 && (
      <p className="m-muted">
        Your message goes to this session on your Mac, the way another
        Claude Code session writes to it. It keeps running in its terminal,
        in its own permission mode, and answers here.
      </p>
    )}
    {timeline.map((entry) =>
      entry.type === "block" ? (
        entry.block.kind === "tools" ? (
          <ToolGroup
            key={entry.block.key}
            group={entry.block}
            open={openKeys.has(entry.block.key)}
            openSteps={openKeys}
            onToggle={() => toggle(entry.block.key)}
            onToggleStep={toggle}
          />
        ) : (
          <Step key={entry.block.key} step={entry.block.step} />
        )
      ) : (
        renderLiveMessage(entry.message)
      ),
    )}
    {error && (
      <p className="m-error" role="alert">
        {error}
      </p>
    )}
    <div ref={end} />
  </main>
  );
}

function PictureTray({ pictures, setPictures }: Pick<LiveState, "pictures" | "setPictures">) {
  return (
    <div className="m-picture-tray" aria-label="Pictures to send">
      {pictures.map((picture) => (
        <span key={picture.key} className="m-picture-chip">
          <img src={picture.preview} alt="Attached picture" />
          <button
            type="button"
            aria-label="Remove picture"
            onClick={() =>
              setPictures((current) =>
                current.filter((item) => item.key !== picture.key),
              )
            }
          >
            <Icon name="close" size={20} />
          </button>
        </span>
      ))}
    </div>
  );
}

async function forkWithMessage(
  session: LiveSession,
  { draft, setForking, setError }: Pick<LiveState, "draft" | "setForking" | "setError">,
  onForked: (started: ForkStarted) => void,
) {
  setForking(true);
  setError("");
  try {
    onForked(await forkLive(session.deviceId, session.peer, draft.trim()));
  } catch (reason) {
    const code = (reason as MobileError).code ?? "";
    setError(FORK_REFUSALS[code] ?? (code ? code.replace(/_/g, " ") : "The copy could not start."));
  } finally {
    setForking(false);
  }
}

function ForkBar({ session, live, onForked }: { session: LiveSession; live: LiveState; onForked: (started: ForkStarted) => void }) {
  const { running, status, draft, forking } = live;
  return (
    <div className="m-fork-bar">
      <span className="m-muted">{forkReason(running, status, draft, forking)}</span>
      <button
        type="button"
        className="m-copy"
        disabled={forkBlocked(running, status, draft, forking)}
        onClick={() => forkWithMessage(session, live, onForked)}
      >
        {forking ? "Starting…" : "Fork with this message"}
      </button>
    </div>
  );
}

function LiveCompose({ live, attach, submit }: {
  live: LiveState;
  attach: (files: FileList | null) => Promise<void>;
  submit: () => Promise<void>;
}) {
  const { picker, busy, running, pictures, draft, setDraft } = live;
  return (
  <footer className="m-compose">
    <input
      ref={picker}
      type="file"
      accept="image/*"
      multiple
      hidden
      onChange={(event) => void attach(event.target.files)}
    />
    <button
      type="button"
      className="m-attach"
      aria-label="Attach a picture"
      disabled={busy || !running || pictures.length >= MAX_PICTURES}
      onClick={() => picker.current?.click()}
    >
      <Icon name="plus" size={20} />
    </button>
    <textarea
      aria-label="Message"
      placeholder={running ? "Write to this session…" : "Not running"}
      value={draft}
      rows={1}
      onChange={(event) => setDraft(event.target.value)}
    />
    <button
      type="button"
      className="m-send"
      aria-label="Send"
      disabled={
        (!draft.trim() && pictures.length === 0) || busy || !running
      }
      onClick={() => void submit()}
    >
      <Icon name="send" size={20} />
    </button>
  </footer>
  );
}

export function LivePage({
  session,
  onBack,
  onForked,
}: {
  session: LiveSession;
  onBack: () => void;
  onForked?: (started: ForkStarted) => void;
}) {
  const live = useLiveSession(session);
  const { running, draft, setDraft, busy, setBusy, setError, pictures, setPictures, progress, allSteps } = live;
  const { picker, end, seen, refresh } = live;

  const steps = progressSteps(progress);
  const blocks = groupSteps(steps);
  const shownBlocks = allSteps ? blocks : blocks.slice(-STEPS_SHOWN);
  const timeline = buildLiveTimeline(shownBlocks, live.messages);
  const items = timeline.length;

  const [newBelow, setNewBelow] = useFollowBottom(items, end, seen);

  const { attach, submit } = liveComposeActions({
    session, draft, setDraft, busy, setBusy, pictures, setPictures, setError, picker, refresh,
  });

  return (
    <div className="m-screen">
      <LiveHeader session={session} status={live.status} messages={live.messages} onBack={onBack} />
      <LiveTimeline live={live} timeline={timeline} hiddenBlocks={blocks.length - shownBlocks.length} stepCount={steps.length} />
      {pictures.length > 0 && <PictureTray pictures={pictures} setPictures={setPictures} />}
      {newBelow && (
        <button
          type="button"
          className="m-new-below"
          onClick={() => {
            end.current?.scrollIntoView?.({ behavior: "smooth" });
            setNewBelow(false);
          }}
        >
          ↓ New steps
        </button>
      )}
      {onForked && <ForkBar session={session} live={live} onForked={onForked} />}
      <LiveCompose live={live} attach={attach} submit={submit} />
    </div>
  );
}
