import type { ReactNode } from "react";

export function MessageBubbleAvatar({
  isUser,
  title,
}: {
  isUser: boolean;
  title: string;
}) {
  const avatarText = (title.trim()[0] || (isUser ? "U" : "A")).toUpperCase();

  return (
    <div
      className={`message-row__avatar ${isUser ? "message-row__avatar--user" : "message-row__avatar--assistant"}`}
      aria-hidden="true"
    >
      {isUser ? (
        <span className="message-row__avatar-text">{avatarText}</span>
      ) : (
        <img
          src="/admin/static/chat/message-logo.svg"
          alt=""
          className="message-row__avatar-image"
        />
      )}
    </div>
  );
}

// The diagnostics Think, Perf and Trace are entries of the message's "⋯" menu (messageMoreMenu.ts),
// which arrives with the other message actions in `headerActions`.
export function MessageBubbleHeader({
  title,
  roleLabel,
  timestamp,
  headerActions,
}: {
  isUser: boolean;
  title: string;
  roleLabel: string;
  timestamp: string;
  headerActions?: ReactNode;
}) {
  return (
    <div className="message-row__header">
      <div className="message-row__identity-main">
        <div className="message-row__identity-line">
          <div className="message-row__participant-title">{title}</div>
          {roleLabel ? <div className="message-row__participant-support">{roleLabel}</div> : null}
        </div>
      </div>
      <div className="message-row__header-side">
        {timestamp ? (
          <div className="message-row__timestamp">{timestamp}</div>
        ) : null}
        {headerActions ? (
          <div className="message-row__header-actions">{headerActions}</div>
        ) : null}
      </div>
    </div>
  );
}
