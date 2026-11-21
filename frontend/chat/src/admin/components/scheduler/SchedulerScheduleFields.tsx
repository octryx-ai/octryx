import { useState } from "react";
import { AdminSchedulerCronHelp } from "../AdminSchedulerCronHelp";
import {
  HOUR_STEPS,
  MINUTE_STEPS,
  MODE_DEFAULTS,
  MODE_LABELS,
  WEEKDAYS,
  compileGuided,
  initialSchedule,
  type GuidedSchedule,
  type ScheduleChoice,
  type ScheduleMode,
  type Weekday,
} from "./scheduleModel";

const DAY_LABELS: Record<Weekday, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

type SchedulerScheduleFieldsProps = {
  /** The exact cron string in the form; remount (key) when another scheduler opens. */
  value: string;
  onChange: (cron: string) => void;
};
type Apply = (next: GuidedSchedule) => void;

// "Every N minutes / hours".
function IntervalField({ schedule, apply }: { schedule: Extract<GuidedSchedule, { mode: "minutes" | "hours" }>; apply: Apply }) {
  return (
    <label className="admin-scheduler__inline">
      Every
      <select
        id="scheduler-schedule-every"
        className="connector-field__input"
        value={schedule.every}
        onChange={(event) =>
          apply({ ...schedule, every: Number(event.target.value) })
        }
      >
        {(schedule.mode === "minutes" ? MINUTE_STEPS : HOUR_STEPS).map(
          (step) => (
            <option key={step} value={step}>
              {step}
            </option>
          ),
        )}
      </select>
      {schedule.mode === "minutes"
        ? "minutes"
        : schedule.every === 1
          ? "hour"
          : "hours"}
    </label>
  );
}

// The weekday checkboxes; at least one day is required.
function WeekdaysField({ schedule, apply }: { schedule: Extract<GuidedSchedule, { mode: "weekdays" }>; apply: Apply }) {
  return (
    <fieldset className="admin-scheduler__days">
      <legend className="admin-panel__form-label">Days</legend>
      {WEEKDAYS.map((day) => (
        <label key={day} className="admin-scheduler__day">
          <input
            type="checkbox"
            checked={schedule.days.includes(day)}
            onChange={(event) =>
              apply({
                ...schedule,
                days: event.target.checked
                  ? [...schedule.days, day]
                  : schedule.days.filter((entry) => entry !== day),
              })
            }
          />
          {DAY_LABELS[day]}
        </label>
      ))}
      {schedule.days.length === 0 ? (
        <div className="admin-panel__form-error">
          Choose at least one day.
        </div>
      ) : null}
    </fieldset>
  );
}

// "At" the time of day, for daily and weekday schedules.
function TimeField({ schedule, apply }: { schedule: Extract<GuidedSchedule, { mode: "daily" | "weekdays" }>; apply: Apply }) {
  return (
    <label className="admin-scheduler__inline">
      At
      <input
        id="scheduler-schedule-time"
        type="time"
        className="connector-field__input"
        value={schedule.time}
        onChange={(event) =>
          apply({ ...schedule, time: event.target.value })
        }
        required
      />
    </label>
  );
}

// The hint before a choice, the cron input for Custom, else the generated cron under "Technical details".
function CronDetails({ mode, value, onChange }: { mode: ScheduleChoice["mode"]; value: string; onChange: (cron: string) => void }) {
  return mode === "unset" ? (
      <div className="admin-form-help">
        Choose how often the action runs: every few minutes or hours, every
        day, or on chosen weekdays. A custom cron expression is the last
        option.
      </div>
    ) : mode === "custom" ? (
      <>
        <input
          id="scheduler-cron"
          aria-label="Cron expression"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          required
          className="connector-field__input"
          spellCheck={false}
          aria-describedby="scheduler-cron-help"
        />
        <AdminSchedulerCronHelp />
      </>
    ) : (
      // The generated cron is an implementation detail of the guided choice.
      <details className="admin-form-help admin-scheduler__technical">
        <summary>Technical details</summary>
        Cron expression: <code>{value || "—"}</code>
      </details>
  );
}

// Guided interval / daily / weekday setup over the single stored cron string.
export function SchedulerScheduleFields({
  value,
  onChange,
}: SchedulerScheduleFieldsProps) {
  const [schedule, setSchedule] = useState<ScheduleChoice>(() =>
    initialSchedule(value),
  );

  const apply = (next: GuidedSchedule) => {
    setSchedule(next);
    if (next.mode !== "custom") onChange(compileGuided(next));
  };
  const chooseMode = (mode: ScheduleMode) =>
    // Custom keeps the current expression as it is; a guided mode starts from its stated default.
    mode === "custom"
      ? setSchedule({ mode: "custom" })
      : apply(MODE_DEFAULTS[mode]);

  return (
    <div className="task-form__field task-form__field--full admin-scheduler__schedule">
      <label
        className="admin-panel__form-label"
        htmlFor="scheduler-schedule-mode"
      >
        Schedule *
      </label>
      <select
        id="scheduler-schedule-mode"
        className="connector-field__input"
        value={schedule.mode === "unset" ? "" : schedule.mode}
        onChange={(event) => chooseMode(event.target.value as ScheduleMode)}
      >
        <option value="" disabled>
          Choose frequency…
        </option>
        {(Object.keys(MODE_LABELS) as ScheduleMode[]).map((mode) => (
          <option key={mode} value={mode}>
            {MODE_LABELS[mode]}
          </option>
        ))}
      </select>

      {schedule.mode === "minutes" || schedule.mode === "hours" ? (
        <IntervalField schedule={schedule} apply={apply} />
      ) : null}

      {schedule.mode === "weekdays" ? (
        <WeekdaysField schedule={schedule} apply={apply} />
      ) : null}

      {schedule.mode === "daily" || schedule.mode === "weekdays" ? (
        <TimeField schedule={schedule} apply={apply} />
      ) : null}

      <CronDetails mode={schedule.mode} value={value} onChange={onChange} />
    </div>
  );
}
