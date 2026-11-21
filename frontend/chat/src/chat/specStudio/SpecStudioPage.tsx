import { useEffect, useRef, useState, type ReactNode } from "react";

import { LoadingState } from "../../layout/LoadingState";
import { PageHeader } from "../../layout/PageHeader";
import { SegmentedTabs } from "../../layout/SegmentedTabs";
import { StatusLabel } from "../../layout/StatusLabel";
import { StudioIcon } from "./specStudioIcons";
import { StudioAcceptance } from "./StudioAcceptance";
import { StudioApprove } from "./StudioApprove";
import { StudioDesign } from "./StudioDesign";
import { StudioOverview } from "./StudioOverview";
import { StudioQuestions } from "./StudioQuestions";
import { StudioRules } from "./StudioRules";
import { useSpecStudio } from "./useSpecStudio";
import "./spec-studio.css";

// The Spec Studio (16./): the product owner sees the spec instead of reading it — a live mock of the
// real screens, questions as choices, rules with worked examples, criteria — decides, pins comments on the mock and
// approves. Desktop and phone are one page: one column on a phone, every tap target 44 px, the desktop mock fully
// visible scaled to the width.

const SECTIONS = [
  { key: "overview", label: "Overview" }, { key: "design", label: "Design" }, { key: "questions", label: "Questions" },
  { key: "rules", label: "Rules" }, { key: "acceptance", label: "Acceptance" }, { key: "approve", label: "Approve" },
];
const POINT_SECTION: Record<string, string> = {
  screens: "design", flow: "overview", design: "design", requirements: "overview", rules: "rules", glossary: "overview",
  conditions: "overview", acceptance: "acceptance",
};

function Section({ id, number, title, purpose, children }: { id: string; number: number; title: string; purpose: string;
  children: ReactNode }) {
  return (
    <section id={`studio-${id}`} className="ds-card studio-section" aria-labelledby={`studio-${id}-title`}>
      <h2 id={`studio-${id}-title`} className="ds-section-title studio-section__title">
        <span className="studio-step" aria-hidden="true">{number}</span>{title}
      </h2>
      <p className="studio-purpose">{purpose}</p>
      {children}
    </section>
  );
}

export function SpecStudioPage({ runId, onBack }: { runId: string; onBack: () => void }) {
  const studio = useSpecStudio(runId);
  const [active, setActive] = useState("overview");
  const page = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!studio.payload || typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (visible) setActive(visible.target.id.replace("studio-", ""));
    }, { rootMargin: "-120px 0px -60% 0px" });
    page.current?.querySelectorAll(".studio-section").forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [studio.payload]);

  const go = (key: string) => {
    setActive(key);
    document.getElementById(`studio-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const { payload } = studio;
  if (!payload) {
    return (
      <main className="studio-page" data-testid="spec-studio">
        {studio.loadError ? (
          <p className="ds-empty" role="alert"><span>The Spec Studio could not be loaded: {studio.loadError}</span>
            <button type="button" className="ds-empty__action ds-link-button" onClick={studio.reload}>Retry</button></p>
        ) : <LoadingState label="Loading the Spec Studio…" />}
      </main>
    );
  }
  const open = payload.open_points.length;
  const status = payload.frozen ? <StatusLabel tone="success" label={`v${payload.approved.length} approved`} />
    : open ? <StatusLabel tone="attention" label={`${open} open point${open === 1 ? "" : "s"}`} />
      : <StatusLabel tone="info" label={payload.awaiting_approval ? "Waiting for you" : "Spec phase at work"} />;
  return (
    <main className="studio-page" ref={page} data-testid="spec-studio">
      <PageHeader eyebrow="Work · Spec" title={payload.artefact.title || payload.title}
        purpose="See the spec instead of reading it: decide, comment on the mock and approve. Every decision is written into SPEC.md."
        secondary={<>
          {status}
          <button type="button" className="ds-btn" onClick={onBack}><StudioIcon name="back" />Back to the run</button>
        </>} />
      <div className="studio-nav">
        <SegmentedTabs label="Spec Studio sections" idPrefix="studio" size="small" value={active} onChange={go}
          tabs={SECTIONS.map((s) => ({ ...s, count: s.key === "approve" && open ? open : undefined }))} />
      </div>
      <div className="studio-sections">
        <Section id="overview" number={1} title="Overview" purpose="What is built, in which stories, and what is left out.">
          <StudioOverview payload={payload} />
        </Section>
        <Section id="design" number={2} title="Design: change it and see it" purpose="Pick a direction, adjust colours and corners, click through the real screens. Comment mode pins a note on any element.">
          <StudioDesign payload={payload} studio={studio} />
        </Section>
        <Section id="questions" number={3} title="Questions for you" purpose="The proposal is preselected. What you choose lands in SPEC.md as a decision.">
          <StudioQuestions payload={payload} studio={studio} />
        </Section>
        <Section id="rules" number={4} title="Rules with examples" purpose="Each worked example becomes a test. Change a value and the spec phase recomputes it.">
          <StudioRules payload={payload} studio={studio} />
        </Section>
        <Section id="acceptance" number={5} title="Acceptance criteria" purpose="Every story is measured against these. Mark one Change and it goes back to the spec phase.">
          <StudioAcceptance payload={payload} studio={studio} />
        </Section>
        <Section id="approve" number={6} title="Approve" purpose="Approval freezes this version and its mock as the review baseline and starts the stories.">
          <StudioApprove payload={payload} studio={studio} onShowPoint={(section) => go(POINT_SECTION[section] ?? "overview")} />
        </Section>
      </div>
    </main>
  );
}
