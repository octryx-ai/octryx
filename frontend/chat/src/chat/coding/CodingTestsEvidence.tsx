import type { CodingValidationEvidence, WorkCodingObservability } from "./codingTypes";
import { readRecordList, validationLabel, validationToolCallLabel, validationTone } from "./codingEvidenceModel";
import type { WorkChangePlan } from "../work/workChangePlanTypes";

type UnknownRecord = Record<string, unknown>;

// The Tests view: recorded validation and the plan's checks are separate sections. A
// planned check is intent and never shown as a result.
export function CodingTestsEvidence({
  sourceFields,
  latestPlan,
  observability,
  validation,
}: {
  sourceFields: UnknownRecord | null;
  latestPlan: Pick<WorkChangePlan, "validation_plan" | "version"> | null;
  observability: WorkCodingObservability | null;
  validation: CodingValidationEvidence;
}) {
  // Well-formed result records only; a missing or malformed field is "not recorded".
  const resultList = readRecordList(sourceFields?.validation_results);
  const resultEntries = resultList?.records ?? null;
  const plannedChecks = Array.isArray(latestPlan?.validation_plan) ? latestPlan.validation_plan : [];
  const toolCalls = validationToolCallLabel(validation);
  return (
    <div className="coding-detail__stack">
      <section className="coding-detail__evidence" aria-label="Recorded validation">
        <h3>Recorded validation</h3>
        <p>
          <span className={`work-badge work-badge--${validationTone(validation)}`}>{validationLabel(validation)}</span>
        </p>
        {resultEntries === null ? (
          <p className="work-detail__empty">No validation results are recorded on the source task.</p>
        ) : resultEntries.length === 0 ? (
          resultList?.unrecognized ? null : <p className="work-detail__empty">The source task records no validation results (0).</p>
        ) : (
          <ul>
            {resultEntries.map((entry, index) => (
              <li key={`result-${index}`}>
                <span>{checkText(entry)}</span>{" "}
                <span className="work-badge">{statusText(entry)}</span>
              </li>
            ))}
          </ul>
        )}
        {resultList?.unrecognized ? (
          <p className="coding-detail__warning">
            {resultList.unrecognized} recorded {resultList.unrecognized === 1 ? "entry is" : "entries are"} not readable, so the
            validation outcome stays open.
          </p>
        ) : null}
        {observability && toolCalls ? (
          <p>{toolCalls}. Tool activity does not confirm that checks passed.</p>
        ) : (
          <p className="work-detail__empty">No agent runtime record is linked, so no tool calls are recorded.</p>
        )}
      </section>
      <section className="coding-detail__evidence" aria-label="Planned checks">
        <h3>Planned checks{latestPlan ? ` (plan v${latestPlan.version})` : ""}</h3>
        <p className="work-detail__empty">The plan's intended checks. They are not results until a run records them.</p>
        {plannedChecks.length === 0 ? (
          <p className="work-detail__empty">The plan lists no checks.</p>
        ) : (
          <ul>
            {plannedChecks.map((entry, index) => (
              <li key={`planned-${index}`}>{checkText(entry)}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function checkText(entry: unknown): string {
  if (typeof entry === "string") return entry;
  const fields = entry && typeof entry === "object" && !Array.isArray(entry) ? (entry as UnknownRecord) : null;
  const named = fields ? fields.command ?? fields.name ?? fields.check ?? fields.title : null;
  return typeof named === "string" && named ? named : JSON.stringify(entry);
}

function statusText(entry: unknown): string {
  const fields = entry && typeof entry === "object" && !Array.isArray(entry) ? (entry as UnknownRecord) : null;
  const status = fields ? fields.status ?? fields.result ?? fields.outcome ?? fields.conclusion : null;
  return typeof status === "string" && status ? status.replaceAll("_", " ") : "no status recorded";
}
