import { Fragment } from "react";

import {
  presentContentObligation,
  type TurnContentObligation,
} from "./turnContentObligations";

// What a content policy did in this turn, inline above the answer (never a toast): masked or routed requests
// and tool results as `--attention`, refusals as `--error`. Names, counts and ids only; never the data.
export function ContentObligationNotices({ notices }: { notices: TurnContentObligation[] }) {
  if (!notices.length) return null;
  return (
    <>
      {notices.map((notice, index) => {
        const view = presentContentObligation(notice);
        return (
          <div
            key={`${notice.decisionId ?? "notice"}-${index}`}
            className={`security-refusal security-refusal--${view.tone}`}
            role={view.tone === "error" ? "alert" : "status"}
            data-testid="content-obligation-notice"
          >
            <div className="security-refusal__head">
              <strong>{view.head}</strong>
              <span className="security-refusal__code">{view.code}</span>
            </div>
            <p className="security-refusal__text">{view.text}</p>
            <dl className="security-refusal__fields">
              {view.fields.map((field) => (
                <Fragment key={field.label}>
                  <dt>{field.label}</dt>
                  <dd>{field.value}</dd>
                </Fragment>
              ))}
            </dl>
            {view.whyHref ? (
              <div className="security-refusal__actions">
                <a className="admin-panel__action-btn" href={view.whyHref} data-testid="content-obligation-why">Why?</a>
              </div>
            ) : null}
          </div>
        );
      })}
    </>
  );
}
