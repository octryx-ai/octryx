import type { CodingExecutionNoticeData } from "./codingExecutionNoticeModel";

export function CodingExecutionNotice({ notice }: { notice: CodingExecutionNoticeData }) {
  return (
    <div className="coding-execution-notice" role="status">
      <div>
        <strong>{notice.title}</strong>
        <span>{notice.message}</span>
      </div>
      <div className="coding-execution-notice__actions">
        {notice.workUrl ? (
          <a className="work-area__button work-area__button--primary" href={notice.workUrl}>
            Open Work Item
          </a>
        ) : null}
        {notice.codingUrl ? (
          <a className="work-area__button" href={notice.codingUrl}>
            Keep Coding View
          </a>
        ) : null}
      </div>
    </div>
  );
}
