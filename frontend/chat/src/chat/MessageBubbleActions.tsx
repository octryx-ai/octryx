import type { ReactNode } from "react";

import { ActionMenu } from "../admin/components/workflowSurfaces/ActionMenu";
import { PencilIcon } from "./ChatShellIcons";
import { CopyIcon, RetryIcon, ReuseIcon } from "./messageBubbleIcons";
import type { MessageMenuItem } from "./messageMoreMenu";

type MessageActionButtonProps = {
  className?: string;
  title: string;
  disabled?: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
  compact?: boolean;
  iconOnly?: boolean;
};

function MessageActionButton({
  className,
  title,
  disabled,
  onClick,
  icon,
  label,
  compact = false,
  iconOnly = false,
}: MessageActionButtonProps) {
  return (
    <button
      type="button"
      className={`message-action-button${compact ? " message-action-button--compact" : ""}${iconOnly ? " message-action-button--icon-only" : ""}${className ? ` ${className}` : ""}`}
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

export function MessageBubbleActions({
  isUser,
  compact = false,
  iconOnly = false,
  isThinking,
  displayContent,
  copied,
  copyMessage,
  actionsDisabled,
  startEditMessage,
  reused,
  reuseMessage,
  retryPrompt,
  retrying,
  triggerRetryFromHere,
  menuItems = [],
}: {
  isUser: boolean;
  compact?: boolean;
  iconOnly?: boolean;
  isThinking: boolean;
  displayContent: string;
  copied: boolean;
  copyMessage: () => Promise<void>;
  actionsDisabled: boolean;
  startEditMessage: () => void;
  reused: boolean;
  reuseMessage: () => void;
  retryPrompt?: string | null;
  retrying: boolean;
  triggerRetryFromHere: () => Promise<void>;
  /** An assistant message shows Copy and Retry; everything else sits in its "⋯" menu (messageMoreMenu). */
  menuItems?: MessageMenuItem[];
}) {
  if (isThinking || !displayContent) {
    return null;
  }

  return (
    <div
      className={`message-row__actions${compact ? " message-row__actions--compact" : ""}`}
    >
      <MessageActionButton
        title="Copy message"
        onClick={() => void copyMessage()}
        icon={<CopyIcon />}
        label={copied ? "Copied" : "Copy"}
        compact={compact}
        iconOnly={iconOnly}
      />
      {isUser ? (
        <MessageActionButton
          title="Edit this message and rerun from here"
          disabled={actionsDisabled}
          onClick={startEditMessage}
          icon={<PencilIcon />}
          label="Edit"
          compact={compact}
          iconOnly={iconOnly}
        />
      ) : null}
      {isUser ? (
        <MessageActionButton
          title="Reuse this message as draft"
          onClick={reuseMessage}
          icon={<ReuseIcon />}
          label={reused ? "Draft ready" : "Draft"}
          compact={compact}
          iconOnly={iconOnly}
        />
      ) : null}
      {!isUser && retryPrompt ? (
        <MessageActionButton
          title="Rerun the thread from this assistant turn"
          disabled={actionsDisabled || retrying}
          onClick={() => void triggerRetryFromHere()}
          icon={<RetryIcon />}
          label={retrying ? "Retrying..." : "Retry"}
          compact={compact}
          iconOnly={iconOnly}
        />
      ) : null}
      {!isUser && menuItems.length ? (
        <ActionMenu row={{ objectName: "this answer" }} items={menuItems} />
      ) : null}
    </div>
  );
}
