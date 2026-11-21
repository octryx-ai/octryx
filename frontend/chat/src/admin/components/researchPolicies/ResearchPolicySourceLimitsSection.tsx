// Source limits section: primary-source, PDF and low-signal toggles.
import { booleanAt } from "./researchPolicySpecHelpers";
import type { ResearchPolicySectionProps } from "./researchPolicyFormShared";

export function ResearchPolicySourceLimitsSection({
  spec,
  setPath,
}: Pick<ResearchPolicySectionProps, "spec" | "setPath">) {
  return (
    <section className="research-policy-admin__form-section">
      <div className="research-policy-admin__form-section-title">
        <span>Source limits</span>
        <small>
          Defines which evidence is acceptable before the document is created.
        </small>
      </div>
      <div className="research-policy-admin__toggle-grid">
        <label>
          <input
            type="checkbox"
            checked={booleanAt(
              spec,
              ["source_policy", "prefer_primary_sources"],
              true,
            )}
            onChange={(event) =>
              setPath(
                ["source_policy", "prefer_primary_sources"],
                event.target.checked,
              )
            }
          />
          Prefer primary sources
        </label>
        <label>
          <input
            type="checkbox"
            checked={booleanAt(
              spec,
              ["source_policy", "prefer_pdf_when_available"],
              true,
            )}
            onChange={(event) =>
              setPath(
                ["source_policy", "prefer_pdf_when_available"],
                event.target.checked,
              )
            }
          />
          Prefer PDFs/Office
        </label>
        <label>
          <input
            type="checkbox"
            checked={booleanAt(
              spec,
              ["source_policy", "reject_low_signal_sources"],
              true,
            )}
            onChange={(event) =>
              setPath(
                ["source_policy", "reject_low_signal_sources"],
                event.target.checked,
              )
            }
          />
          Reject low-signal sources
        </label>
      </div>
    </section>
  );
}
