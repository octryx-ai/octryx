import { useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { formatExactTime, formatRelative } from "../../admin/utils/dateTime";
import { ActionMenu } from "../../admin/components/workflowSurfaces/ActionMenu";
import { requestActionNeededRefresh } from "../agents/actionNeededRefresh";
import { sendAttentionAction } from "./companionApi";
import { acceptedSessionId, isHandoverAccept } from "./companionHandoverModel";
import { cardActions, cardParts, itemTitle } from "./companionLabels";
import { buildActionRequest, countdownText, secondsLeft } from "./companionModel";
import { type AttentionAction, type AttentionItem } from "./companionTypes";

// One attention card: a short title, the text rendered as Markdown (no raw HTML), the
// decisions as buttons; stop and abort in the ⋯ menu, their reason asked only after the choice. An answered card
// says "Answered" where it stands; the panel removes it after a moment, so nothing jumps under the pointer.

export type Accepted = (sessionId: string | null) => void;

const TONE_CLASS = { primary: " admin-panel__action-btn--primary", danger: " admin-panel__action-btn--danger", neutral: "" };
const HEADING = ({ children }: { children?: ReactNode }) => <p className="octryx-panel__text-heading">{children}</p>;

export function CompanionMarkdown({ text }: { text: string }) {
  return (
    <div className="octryx-panel__text" data-testid="octryx-item-text">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml
        components={{
          h1: HEADING, h2: HEADING, h3: HEADING, h4: HEADING, h5: HEADING, h6: HEADING, img: () => null,
          a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
        }}>
        {text.trim()}
      </ReactMarkdown>
    </div>
  );
}

function ItemActions({ item, onAnswered, onAccepted }: { item: AttentionItem; onAnswered: (key: string) => void; onAccepted: Accepted }) {
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A menu action with a text input (stop with its reason) shows its field only once chosen.
  const [chosen, setChosen] = useState<string | null>(null);
  const { decisions, menu } = cardActions(item);

  const run = (action: AttentionAction) => {
    const request = buildActionRequest(action, texts[action.key] ?? "");
    if ("error" in request) { setError(request.error); return; }
    setBusy(action.key);
    setError(null);
    sendAttentionAction(request).then((answer) => {
      requestActionNeededRefresh();
      if (isHandoverAccept(item, action)) onAccepted(acceptedSessionId(answer));
      onAnswered(item.key);
    }).catch((failure: { message?: string }) => {
      setBusy(null);
      setError(failure?.message || "The server did not accept this.");
    });
  };

  const field = (action: AttentionAction) => (
    <form key={action.key} className="octryx-panel__answer" onSubmit={(event) => { event.preventDefault(); run(action); }}>
      <label className="admin-panel__field">
        <span>{action.input?.label || action.label}</span>
        <input type="text" className="admin-panel__input" value={texts[action.key] ?? ""} placeholder={action.input?.placeholder}
          required={action.input?.required} disabled={busy !== null} data-testid="octryx-answer-input"
          onChange={(event) => setTexts((current) => ({ ...current, [action.key]: event.target.value }))} />
      </label>
      <button type="submit" className={`admin-panel__action-btn${TONE_CLASS[action.tone]}`} disabled={busy !== null}
        data-testid="octryx-answer-send">
        {busy === action.key ? "Sending…" : action.label}
      </button>
    </form>
  );
  const buttons = decisions.filter((action) => action.input?.kind !== "text");
  const chosenAction = menu.find((action) => action.key === chosen) ?? null;
  return (
    <div className="octryx-panel__actions">
      {buttons.length || menu.length ? (
        <div className="octryx-panel__buttons">
          {buttons.map((action) => (
            <button key={action.key} type="button" className={`admin-panel__action-btn${TONE_CLASS[action.tone]}`}
              disabled={busy !== null} onClick={() => run(action)} data-testid="octryx-action">
              {busy === action.key ? "Sending…" : action.label}
            </button>
          ))}
          {menu.length ? (
            <ActionMenu row={{ objectName: itemTitle(item) }} items={menu.map((action) => ({
              label: action.label, danger: true, disabled: busy !== null,
              onSelect: () => (action.input?.kind === "text" ? setChosen(action.key) : run(action)),
            }))} />
          ) : null}
        </div>
      ) : null}
      {decisions.filter((action) => action.input?.kind === "text").map(field)}
      {chosenAction ? field(chosenAction) : null}
      {error ? <p className="octryx-panel__refusal" role="alert" data-testid="octryx-refusal">{error}</p> : null}
    </div>
  );
}

export function ItemCard({ item, now, answered, onAnswered, onAccepted }: {
  item: AttentionItem; now: number; answered: boolean; onAnswered: (key: string) => void; onAccepted: Accepted;
}) {
  const left = secondsLeft(item.expiresAt, now);
  const title = itemTitle(item);
  const { subtitle, meta, body } = cardParts(item, title);
  return (
    <li className={`octryx-panel__item octryx-panel__item--${item.kind}${answered ? " octryx-panel__item--answered" : ""}`}
      data-testid="octryx-item" data-kind={item.kind} aria-busy={answered || undefined}>
      <strong className="octryx-panel__item-title">{title}</strong>
      {subtitle ? <span className="octryx-panel__meta">{subtitle}</span> : null}
      <span className="octryx-panel__meta">
        {meta.join(" · ")}
        {item.createdAt ? <> · <time title={formatExactTime(item.createdAt)}>{formatRelative(item.createdAt, "", now)}</time></> : null}
      </span>
      {answered ? <p className="octryx-panel__answered" role="status" data-testid="octryx-answered">Answered</p> : (
        <>
          {body ? <CompanionMarkdown text={body} /> : null}
          {left !== null ? <span className="octryx-panel__countdown" data-testid="octryx-countdown">{countdownText(left)}</span> : null}
          {item.actions.length ? <ItemActions item={item} onAnswered={onAnswered} onAccepted={onAccepted} /> : null}
          {item.link ? <a className="octryx-panel__link" href={item.link.href}>{item.link.label} →</a> : null}
        </>
      )}
    </li>
  );
}
