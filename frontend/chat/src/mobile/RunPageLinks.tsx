// The run page's links: the run's chat and its Work item.
import type { ReactNode } from "react";
import { Icon } from "./icons";
import type { RunPayload } from "./useRunPage";
import type { RunLinks } from "./RunPage";

function LinkRow({ icon, title, detail, onClick }: { icon: "chats" | "work"; title: ReactNode; detail: string; onClick: () => void }) {
  return (
    <li>
      <button type="button" className="m-row m-row-icon" onClick={onClick}>
        <span className="m-row-glyph" aria-hidden="true">
          <Icon name={icon} size={20} />
        </span>
        <span className="m-row-text">
          <b>{title}</b>
          <span>{detail}</span>
        </span>
        <Icon name="chevronRight" size={18} className="m-row-chevron" />
      </button>
    </li>
  );
}

export function RunPageLinks({ run, session, subject, links }: {
  run: RunPayload;
  session: string;
  subject: string;
  links: RunLinks;
}) {
  const item = run.work_item;
  return (
    <ul className="m-rows m-group">
      {session && (
        <LinkRow icon="chats" title="The run's chat" detail="What the agents did and said"
          onClick={() => links.onOpenChat(session, subject, run.project_id ?? "")} />
      )}
      {item && (
        <LinkRow icon="work" title={<>Work item {item.key}</>} detail="Ticket, plan and comments"
          onClick={() =>
            links.onOpenWorkItem({
              id: item.id,
              key: item.key,
              title: item.title,
              state: item.state ?? "",
              projectId: run.project_id ?? "",
            })
          } />
      )}
    </ul>
  );
}
