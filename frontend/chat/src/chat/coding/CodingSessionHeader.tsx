import { ActionMenu } from "../../admin/components/workflowSurfaces/ActionMenu";
import { useConfirmAction } from "../../admin/components/confirm/useConfirmAction";
import type { CodingSessionSummary } from "./codingTypes";
import type { CodingNextAction, CodingSectionKey } from "./codingSessionSteps";

// The top of a Coding session: work item key and title, one state word, the next action as the
// one primary control, Open Work Item, Start agent (neutral unless it is the next action, with its reason while it
// waits) and "Restart from scratch" last in the ⋯ menu, confirmed by the session's name.
export function CodingSessionHeader({
  session,
  nextAction,
  canStartAgent,
  startReason,
  startingAgent,
  onStartAgent,
  onRestartAgent,
  onOpenSection,
}: {
  session: CodingSessionSummary;
  nextAction: CodingNextAction;
  canStartAgent: boolean;
  startReason: string;
  startingAgent: boolean;
  onStartAgent: () => void;
  onRestartAgent: () => void;
  onOpenSection: (section: CodingSectionKey) => void;
}) {
  const { ask, dialog, notice } = useConfirmAction();
  const agent = session.latestAgentSession;
  const startIsNext = nextAction?.kind === "start";
  const completed = session.state === "completed";
  const startLabel = startingAgent ? "Starting..." : agent ? "Start another run" : "Start agent";
  const name = session.sourceKey;
  const restart = () =>
    ask({
      title: `Restart ${name} from scratch?`,
      body: "The current result is declined and stays as audit evidence. A fresh run starts from the approved plan.",
      confirmLabel: `Restart ${name}`,
      tone: "danger",
      run: async () => onRestartAgent(),
      done: `${name} restarts from scratch.`,
    });
  return (
    <header className="coding-detail__header">
      <div>
        <div className="work-area__eyebrow">Coding session</div>
        <h2>
          {session.sourceKey} <span className="coding-detail__title">{session.title}</span>
        </h2>
        <span className={`work-badge work-badge--${session.tone}`}>{session.statusLabel}</span>
        {notice ? <p className="coding-detail__notice" role="status">{notice}</p> : null}
      </div>
      <div className="coding-detail__header-actions">
        {nextAction?.kind === "link" ? (
          <a className="work-area__button work-area__button--primary" href={nextAction.href}
            {...(nextAction.external ? { target: "_blank", rel: "noreferrer" } : {})}>
            {nextAction.label}
          </a>
        ) : null}
        {nextAction?.kind === "section" ? (
          <button type="button" className="work-area__button work-area__button--primary" onClick={() => onOpenSection(nextAction.section)}>
            {nextAction.label}
          </button>
        ) : null}
        <a className="work-area__button" href={`/chat?area=work&work_item_id=${encodeURIComponent(session.id)}`}>
          Open Work Item
        </a>
        {agent && nextAction?.kind !== "link" ? (
          <a className="work-area__button" href={agent.chat_url}>Open task chat</a>
        ) : null}
        {/* A completed session starts nothing more: no disabled Start agent with "The session is complete." */}
        {completed ? null : (
          <button
            type="button"
            className={`work-area__button${startIsNext ? " work-area__button--primary" : ""}`}
            onClick={onStartAgent}
            disabled={!canStartAgent || startingAgent}
            title={!canStartAgent && startReason ? startReason : undefined}
          >
            {startLabel}
          </button>
        )}
        {agent ? (
          <ActionMenu
            row={{ objectName: name }}
            buttonClassName="work-area__button"
            items={[{ label: "Restart from scratch", danger: true, disabled: !canStartAgent || startingAgent, onSelect: restart }]}
          />
        ) : null}
        {!completed && !canStartAgent && startReason ? <span className="coding-detail__hint">{startReason}</span> : null}
      </div>
      {dialog}
    </header>
  );
}
