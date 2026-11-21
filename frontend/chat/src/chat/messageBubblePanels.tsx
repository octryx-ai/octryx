import type { ReactNode } from "react";

import { extractPerformanceSections } from "./messageBubbleHelpers";

export type PerformanceSections = ReturnType<typeof extractPerformanceSections>;

export function MessageThinkingPanel({
  isUser,
  hasTurnTrace,
  thinkingOpen,
  thinkingText,
  thinkingUnavailable,
  onToggleThinking,
}: {
  isUser: boolean;
  hasTurnTrace: boolean;
  thinkingOpen: boolean;
  thinkingText: string;
  thinkingUnavailable: boolean;
  onToggleThinking: () => Promise<void>;
}) {
  if (isUser || !hasTurnTrace) {
    return null;
  }

  return (
    <div className="message-thinking-panel">
      {thinkingOpen && thinkingText ? (
        <button
          type="button"
          className="message-thinking-panel__card"
          onClick={() => void onToggleThinking()}
        >
          <div className="message-thinking-panel__header">
            <span className="message-thinking-panel__title">Thinking</span>
            <span className="message-thinking-panel__hint">
              Click to collapse
            </span>
          </div>
          <pre className="message-thinking-panel__content">{thinkingText}</pre>
        </button>
      ) : null}
      {thinkingUnavailable ? (
        <div className="message-thinking-panel__empty">
          This response did not include visible thinking.
        </div>
      ) : null}
    </div>
  );
}

function PerformanceSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="message-performance-panel__section">
      <div className="message-performance-panel__section-title">{title}</div>
      {children}
    </div>
  );
}

function PerformanceListItem({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="message-performance-panel__list-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function CodeIntelligenceSection({ codeIntelligence }: { codeIntelligence: PerformanceSections["codeIntelligence"] }) {
  return (
    <PerformanceSection title="Code intelligence">
      {codeIntelligence.repositoryBackends ? (
        <div className="message-performance-panel__list">
          <PerformanceListItem
            label="Effective repo backends"
            value={Object.entries(codeIntelligence.repositoryBackends)
              .map(([key, value]) => `${key} ${value}`)
              .join(" · ")}
          />
        </div>
      ) : null}
      {codeIntelligence.rows.length ? (
        <div className="message-performance-panel__list">
          {codeIntelligence.rows.map((row) => (
            <PerformanceListItem key={row.label} label={row.label} value={row.value} />
          ))}
        </div>
      ) : null}
    </PerformanceSection>
  );
}

function PerformanceCard({ performance }: { performance: PerformanceSections }) {
  return (
    <div className="message-performance-panel__card">
      <div className="message-performance-panel__header">
        <span className="message-performance-panel__title">Performance</span>
      </div>
      {performance.summary.length ? (
        <div className="message-performance-panel__grid">
          {performance.summary.map((item) => (
            <div key={item.label} className="message-performance-panel__stat">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {performance.modelSteps.length ? (
        <PerformanceSection title="Model steps">
          <div className="message-performance-panel__list">
            {performance.modelSteps.map((step) => (
              <PerformanceListItem key={step.label} label={step.label} value={step.value} />
            ))}
          </div>
        </PerformanceSection>
      ) : null}
      {performance.toolSteps.length ? (
        <PerformanceSection title="Tool steps">
          <div className="message-performance-panel__list">
            {performance.toolSteps.map((step) => (
              <PerformanceListItem key={step.id} label={<>{step.label} · {step.status}</>} value={step.value} />
            ))}
          </div>
        </PerformanceSection>
      ) : null}
      {performance.runtimeAttempts.length ? (
        <PerformanceSection title="Runtime attempts">
          <div className="message-performance-panel__list">
            {performance.runtimeAttempts.map((attempt) => (
              <PerformanceListItem
                key={attempt.id}
                label={<>{attempt.label} · {attempt.status}{attempt.error ? ` · ${attempt.error}` : ""}</>}
                value={attempt.value || "—"}
              />
            ))}
          </div>
        </PerformanceSection>
      ) : null}
      {performance.codeIntelligence.hasData ? (
        <CodeIntelligenceSection codeIntelligence={performance.codeIntelligence} />
      ) : null}
    </div>
  );
}

export function MessagePerformancePanel({
  isUser,
  performanceOpen,
  performance,
  performanceUnavailable,
}: {
  isUser: boolean;
  performanceOpen: boolean;
  performance: PerformanceSections;
  performanceUnavailable: boolean;
}) {
  if (isUser) {
    return null;
  }

  return (
    <div className="message-performance-panel">
      {performanceOpen && performance.hasPerformance ? <PerformanceCard performance={performance} /> : null}
      {performanceUnavailable ? (
        <div className="message-performance-panel__empty">
          No performance metrics were captured for this response.
        </div>
      ) : null}
    </div>
  );
}
