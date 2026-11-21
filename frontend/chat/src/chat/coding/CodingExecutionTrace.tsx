import type { CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import { buildTraceSteps, isHttpUrl } from "./codingTraceSteps";
import type { WorkChangePlan } from "../work/workChangePlanTypes";

type ExecutionTraceProps = {
  session: CodingSessionSummary;
  detail: CodingSessionDetailData | null;
  latestPlan: WorkChangePlan | null;
};

export function CodingExecutionTrace({ session, detail, latestPlan }: ExecutionTraceProps) {
  const steps = buildTraceSteps(session, detail, latestPlan);
  return (
    <section className="coding-execution-trace" aria-label="Coding execution trace">
      <header className="coding-execution-trace__header">
        <div>
          <div className="work-area__eyebrow">Execution trace</div>
          <h3>{session.sourceKey}</h3>
        </div>
        <span className={`work-badge work-badge--${session.tone}`}>{session.statusLabel}</span>
      </header>
      <ol className="coding-execution-trace__steps">
        {steps.map((step) => (
          <li key={step.key} className={`coding-execution-trace__step is-${step.tone}`}>
            <span className="coding-execution-trace__rail" />
            <div className="coding-execution-trace__content">
              <div className="coding-execution-trace__topline">
                <div>
                  <strong>{step.label}</strong>
                  <small>{step.summary}</small>
                </div>
                <span className={`work-badge work-badge--${step.tone}`}>{step.status}</span>
              </div>
              {step.meta.length ? (
                <div className="coding-execution-trace__meta">
                  {step.meta.map((entry) => (
                    <span key={`${step.key}-${entry}`}>{entry}</span>
                  ))}
                </div>
              ) : null}
              {step.links.length ? (
                <div className="coding-execution-trace__links">
                  {step.links.map((link) => (
                    <TraceLink key={`${step.key}-${link.label}-${link.href || ""}`} link={link} />
                  ))}
                </div>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function TraceLink({ link }: { link: { label: string; href?: string | null } }) {
  if (!link.href || !isLinkHref(link.href)) {
    return <span>{link.label}</span>;
  }
  const external = isHttpUrl(link.href);
  return (
    <a href={link.href} target={external ? "_blank" : undefined} rel={external ? "noreferrer" : undefined}>
      {link.label}
    </a>
  );
}


function isLinkHref(value: string): boolean {
  return isHttpUrl(value) || value.startsWith("/");
}
