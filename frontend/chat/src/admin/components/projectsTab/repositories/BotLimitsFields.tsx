import { useState } from "react";

import { ChipListEditor } from "../../settingsKit/SettingsKit";
import {
  FIX_RUNS_HINT, HOTSPOT_HINT, LIMIT_MAX, LIMIT_MIN, SIZE_HINT, parseLimit, type BotLimits, type LimitErrors,
} from "./prReviewBotLimits";

// A PR review bot card's fields beyond the trigger: fix runs, the size brake and the repository's own hotspot paths.
// The draft lives in the card; this component only shows it and reports changes.
export function BotLimitsFields({ draft, errors, disabled, name, testId, onChange }: {
  draft: BotLimits;
  errors: LimitErrors;
  disabled: boolean;
  name: string;
  testId: string;
  onChange: (patch: Partial<BotLimits>) => void;
}) {
  // What the person typed, so "12a" stays visible next to its problem instead of turning into NaN.
  const [typed, setTyped] = useState<{ lines?: string; files?: string }>({});
  const limit = (key: "lines" | "files", value: number) => typed[key] ?? (Number.isNaN(value) ? "" : String(value));
  const setLimit = (key: "lines" | "files", text: string) => {
    setTyped((current) => ({ ...current, [key]: text }));
    onChange(key === "lines" ? { sizeLimitLines: parseLimit(text) } : { sizeLimitFiles: parseLimit(text) });
  };
  return (
    <>
      <div className="review-bot__field">
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={draft.fixRuns} disabled={disabled} data-testid={`${testId}-fix-runs`}
            onChange={(event) => onChange({ fixRuns: event.target.checked })} />
          <span>Fix runs</span>
        </label>
        <p className="sk-muted">{FIX_RUNS_HINT}</p>
      </div>

      <div className="review-bot__field">
        <div className="review-bot__label">Size brake</div>
        <div className="sk-row review-bot__limits">
          <label className="admin-panel__field">Lines
            <input className="admin-panel__input" inputMode="numeric" value={limit("lines", draft.sizeLimitLines)}
              disabled={disabled} aria-label={`Line limit of ${name}`} aria-invalid={Boolean(errors.sizeLimitLines)}
              min={LIMIT_MIN} max={LIMIT_MAX} data-testid={`${testId}-lines`}
              onChange={(event) => setLimit("lines", event.target.value)} />
          </label>
          <label className="admin-panel__field">Files
            <input className="admin-panel__input" inputMode="numeric" value={limit("files", draft.sizeLimitFiles)}
              disabled={disabled} aria-label={`File limit of ${name}`} aria-invalid={Boolean(errors.sizeLimitFiles)}
              min={LIMIT_MIN} max={LIMIT_MAX} data-testid={`${testId}-files`}
              onChange={(event) => setLimit("files", event.target.value)} />
          </label>
        </div>
        <p className="sk-muted">{SIZE_HINT}</p>
        {errors.sizeLimitLines ? <p className="sk-err" role="alert">Lines: {errors.sizeLimitLines}</p> : null}
        {errors.sizeLimitFiles ? <p className="sk-err" role="alert">Files: {errors.sizeLimitFiles}</p> : null}
      </div>

      <div className="review-bot__field">
        <div className="review-bot__label">Hotspot paths</div>
        <ChipListEditor label={`hotspot paths of ${name}`} values={draft.hotspotPaths} disabled={disabled}
          testId={`${testId}-hotspots`} problems={errors.hotspots} onChange={(hotspotPaths) => onChange({ hotspotPaths })} />
        <p className="sk-muted">{HOTSPOT_HINT}</p>
        {errors.hotspotPaths ? <p className="sk-err" role="alert">{errors.hotspotPaths}</p> : null}
      </div>
    </>
  );
}
