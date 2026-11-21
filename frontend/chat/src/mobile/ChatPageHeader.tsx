// The head of a mobile chat: back, title, the job's run line and context use, and copy of the whole chat.

import type { DeviceJob } from "../chat/devices/deviceJobTypes";
import { compactions, contextLabel, contextUsage } from "./mobileUsageModel";
import { folderName } from "./mobileDeviceChats";
import { routeLabel, routeSuggestion } from "./mobileTurnOptions";
import { runLine } from "./engineSeatModel";
import { RunLineSubline } from "./RunLine";
import { Icon } from "./icons";
import { copy } from "./mobileChatBrowser";
import type { Message } from "./chatPageMessages";

export function ChatPageHeader({ title, forkThreadId, job, context, compacted, route, messages, onBack }: {
  title: string;
  forkThreadId?: string;
  job: DeviceJob | null;
  context: ReturnType<typeof contextUsage> | null;
  compacted: ReturnType<typeof compactions>;
  route: ReturnType<typeof routeSuggestion> | null;
  messages: Message[];
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
      <strong>
        {title || "Chat"}
        {forkThreadId && <span className="m-tag">Fork</span>}
      </strong>
      {job && (
        // Engine, route and model of the job (reported model, else the one the chat asked for), then the Mac.
        <RunLineSubline
          line={runLine({ engine: job.engine, profile: job.profile, model: job.model || job.requestedModel })}
          more={[job.deviceName, folderName(job.folder)]}
        />
      )}
      {context && (
        <span
          className={`m-context${(context.percent ?? 0) >= 90 ? " m-context-full" : (context.percent ?? 0) >= 70 ? " m-context-high" : ""}`}
        >
          {contextLabel(context)}
          {compacted.count
            ? ` · compacted ${compacted.count}× (−${Math.round(compacted.freed / 1000)}k)`
            : ""}
        </span>
      )}
      {route && <span className="m-context">{routeLabel(route)}</span>}
    </div>
    {messages.length > 0 && (
      <button
        type="button"
        className="m-icon-button"
        aria-label="Copy the whole chat"
        onClick={() =>
          copy(
            messages
              .map(
                (message) =>
                  `${message.role === "user" ? "You" : "Claude"}: ${message.content}`,
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
