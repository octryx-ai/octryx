// One chat message of a live session: the person's message with its delivery state, or the session's answer.

import { MarkdownRenderer } from "../chat/MarkdownRenderer";
import { liveDeliveryLabel, type LiveMessage } from "./mobileLiveSessions";
import { shortTime } from "./mobileUsageModel";
import { copy, theme } from "./mobileChatBrowser";

export function renderLiveMessage(message: LiveMessage) {
  return message.direction === "out" ? (
    <div key={message.id}>
      <div className="m-user">
        {message.attachments > 0 && message.text === "(picture)"
          ? null
          : message.text}
        {message.attachments > 0 && (
          <span className="m-live-pictures">
            📎 {message.attachments}{" "}
            {message.attachments === 1 ? "picture" : "pictures"}
          </span>
        )}
      </div>
      <span
        className={`m-live-state${message.state === "delivered" || message.state === "pending" || message.state === "sent" ? "" : " m-live-failed"}`}
      >
        {liveDeliveryLabel(message)} ·{" "}
        {shortTime(message.createdAt)}
      </span>
    </div>
  ) : (
    <div key={message.id}>
      <div className="m-ai m-ai-md">
        <MarkdownRenderer content={message.text} theme={theme()} />
      </div>
      <button
        type="button"
        className="m-copy"
        onClick={() => copy(message.text)}
      >
        Copy
      </button>
    </div>
  );
}
