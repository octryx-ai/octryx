import type { ReactNode } from "react";
import { StatusLabel } from "../layout/StatusLabel";
import { TRUSTED_BADGE, type RoleChatNotice } from "./roles/myRoleModel";

type ComposerNoticeProps = {
  tone?: "editing" | "resume" | "auto-agent" | "task" | "role-empty" | "plan";
  label: string;
  text: ReactNode;
  action?: ReactNode;
};

function ComposerNotice({ tone, label, text, action }: ComposerNoticeProps) {
  return (
    <div
      className={`composer-notice${tone ? ` composer-notice--${tone}` : ""}`}
    >
      <div className="composer-notice__body">
        <span className="composer-notice__label">{label}</span>
        <span className="composer-notice__text">{text}</span>
      </div>
      {action ? <div className="composer-notice__action">{action}</div> : null}
    </div>
  );
}

/**
 * The person's roles in the chat's Workspace (roles contract §4/§5): with role-based tools on and no role, a calm
 * attention banner (the chat still answers, without tools); while a trusted role applies, a small persistent line.
 */
function RoleNotice({ notice }: { notice: RoleChatNotice }) {
  if (notice.kind === "empty") {
    return (
      <div className="composer-notice composer-notice--role-empty" role="status" data-testid="role-empty-notice">
        <div className="composer-notice__body">
          <span className="composer-notice__label">No tools in {notice.workspace || "this Workspace"}</span>
          <span className="composer-notice__text">{notice.text}</span>
          <span className="composer-notice__hint">{notice.hint} You can keep chatting; answers come without tools.</span>
        </div>
      </div>
    );
  }
  return (
    <div className="composer-role-line" data-testid="role-trusted-notice">
      <StatusLabel label={TRUSTED_BADGE} tone="attention" />
      <span className="composer-role-line__text">
        {notice.text}
      </span>
    </div>
  );
}

// The route (workflow and why) is not shown above the composer: it is under "Run details" in the chat
// header.
export function ComposerNotices({
  editingMessage,
  onCancelEditMessage,
  resumeComposerCopy,
  generateTaskResult,
  setGenerateTaskResult,
  agentNotice,
  roleNotice,
  planNotice,
}: {
  editingMessage: { id: string; content: string } | null;
  onCancelEditMessage: () => void;
  resumeComposerCopy: string | null;
  generateTaskResult: { taskName: string; taskUrl: string } | null;
  setGenerateTaskResult: (
    result: { taskName: string; taskUrl: string } | null,
  ) => void;
  // Persistent while composing: a requested agent this chat's next message does not use.
  agentNotice?: { text: string; href: string } | null;
  // Persistent while the chat's Workspace applies role-based tools (roles contract §4/§5).
  roleNotice?: RoleChatNotice | null;
  // The write plan confirmed for this request: a quiet line while it is active.
  planNotice?: string | null;
}) {
  const hasNotice =
    Boolean(roleNotice) ||
    Boolean(planNotice) ||
    Boolean(agentNotice) ||
    Boolean(editingMessage) ||
    Boolean(resumeComposerCopy) ||
    Boolean(generateTaskResult);

  if (!hasNotice) {
    return null;
  }

  return (
    <div className="composer-notices">
      {roleNotice ? <RoleNotice notice={roleNotice} /> : null}
      {planNotice ? <ComposerNotice tone="plan" label="Write plan" text={planNotice.replace(/^Write plan /, "")} /> : null}
      {agentNotice ? (
        <ComposerNotice
          tone="auto-agent"
          label="Agent not selected"
          text={agentNotice.text}
          action={<a href={agentNotice.href}>Open Agents</a>}
        />
      ) : null}
      {editingMessage ? (
        <ComposerNotice
          tone="editing"
          label="Editing"
          text="Sending now will rerun this thread from that point and discard later turns."
          action={
            <button
              type="button"
              className="composer-notice__close"
              onClick={onCancelEditMessage}
            >
              Cancel
            </button>
          }
        />
      ) : null}
      {resumeComposerCopy ? (
        <ComposerNotice
          tone="resume"
          label="Resume"
          text={resumeComposerCopy}
        />
      ) : null}
      {generateTaskResult ? (
        <ComposerNotice
          tone="task"
          label="Draft created"
          text={
            <>
              <strong>{generateTaskResult.taskName}</strong> is ready for
              follow-up.
            </>
          }
          action={
            <>
              <a
                href={generateTaskResult.taskUrl}
                target="_blank"
                rel="noreferrer"
              >
                Open
              </a>
              <button
                type="button"
                className="composer-notice__close"
                onClick={() => setGenerateTaskResult(null)}
              >
                Dismiss
              </button>
            </>
          }
        />
      ) : null}
    </div>
  );
}
