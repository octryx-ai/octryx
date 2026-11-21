// Guided scheduler authoring and the save gate.
//
// The stored value stays one cron string with APScheduler semantics. Guided modes compile to
// cron with weekday *names* only, so the numeric Monday = 0 rule is never involved. A stored
// expression opens in a guided mode only when compiling it back gives the exact same string;
// anything else (numeric weekdays, ranges, steps) opens as Custom, byte-for-byte.

export const MINUTE_STEPS = [5, 10, 15, 20, 30] as const;
export const HOUR_STEPS = [1, 2, 3, 4, 6, 8, 12] as const;
export const WEEKDAYS = [
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
  "sun",
] as const;
export type Weekday = (typeof WEEKDAYS)[number];

export type GuidedSchedule =
  | { mode: "minutes"; every: number }
  | { mode: "hours"; every: number }
  | { mode: "daily"; time: string }
  | { mode: "weekdays"; days: Weekday[]; time: string }
  | { mode: "custom" };

export type ScheduleMode = GuidedSchedule["mode"];

export const MODE_LABELS: Record<ScheduleMode, string> = {
  minutes: "Every few minutes",
  hours: "Every few hours",
  daily: "Every day",
  weekdays: "On chosen weekdays",
  custom: "Custom cron expression",
};

// Starting values when the admin switches to a guided mode; never applied silently.
export const MODE_DEFAULTS: Record<
  Exclude<ScheduleMode, "custom">,
  GuidedSchedule
> = {
  minutes: { mode: "minutes", every: 15 },
  hours: { mode: "hours", every: 1 },
  daily: { mode: "daily", time: "09:00" },
  weekdays: {
    mode: "weekdays",
    days: ["mon", "tue", "wed", "thu", "fri"],
    time: "09:00",
  },
};

function clock(time: string): [number, number] | null {
  const match = /^(\d{2}):(\d{2})$/.exec(time);
  if (!match) return null;
  const [hour, minute] = [Number(match[1]), Number(match[2])];
  return hour < 24 && minute < 60 ? [hour, minute] : null;
}

// Runs of three or more consecutive days become a range (mon-fri), shorter runs a list.
function weekdayField(days: Weekday[]): string {
  const indexes = WEEKDAYS.map((_, index) => index).filter((index) =>
    days.includes(WEEKDAYS[index]),
  );
  const parts: string[] = [];
  for (let start = 0; start < indexes.length; ) {
    let end = start;
    while (end + 1 < indexes.length && indexes[end + 1] === indexes[end] + 1)
      end += 1;
    const run = indexes.slice(start, end + 1).map((index) => WEEKDAYS[index]);
    parts.push(
      run.length >= 3 ? `${run[0]}-${run[run.length - 1]}` : run.join(","),
    );
    start = end + 1;
  }
  return parts.join(",");
}

/** The cron string for a guided choice, or "" while the choice is incomplete. */
export function compileGuided(schedule: GuidedSchedule): string {
  switch (schedule.mode) {
    case "minutes":
      return (MINUTE_STEPS as readonly number[]).includes(schedule.every)
        ? `*/${schedule.every} * * * *`
        : "";
    case "hours":
      return (HOUR_STEPS as readonly number[]).includes(schedule.every)
        ? `0 */${schedule.every} * * *`
        : "";
    case "daily": {
      const parsed = clock(schedule.time);
      return parsed ? `${parsed[1]} ${parsed[0]} * * *` : "";
    }
    case "weekdays": {
      const parsed = clock(schedule.time);
      return parsed && schedule.days.length
        ? `${parsed[1]} ${parsed[0]} * * ${weekdayField(schedule.days)}`
        : "";
    }
    default:
      return "";
  }
}

const pad = (value: number) => String(value).padStart(2, "0");

function parseWeekdays(field: string): Weekday[] | null {
  const days: Weekday[] = [];
  for (const part of field.split(",")) {
    const [from, to = from] = part.split("-");
    const [start, end] = [
      WEEKDAYS.indexOf(from as Weekday),
      WEEKDAYS.indexOf(to as Weekday),
    ];
    if (start < 0 || end < start) return null;
    for (let index = start; index <= end; index += 1)
      days.push(WEEKDAYS[index]);
  }
  return days;
}

function candidate(expression: string): GuidedSchedule | null {
  const fields = expression.split(" ");
  if (fields.length !== 5) return null;
  const [minute, hour, day, month, weekday] = fields;
  const step = (value: string) =>
    /^\*\/\d+$/.test(value) ? Number(value.slice(2)) : NaN;
  if (hour === "*" && day === "*" && month === "*" && weekday === "*")
    return { mode: "minutes", every: step(minute) };
  if (
    minute === "0" &&
    day === "*" &&
    month === "*" &&
    weekday === "*" &&
    hour.startsWith("*/")
  )
    return { mode: "hours", every: step(hour) };
  if (
    !/^\d{1,2}$/.test(minute) ||
    !/^\d{1,2}$/.test(hour) ||
    day !== "*" ||
    month !== "*"
  )
    return null;
  const time = `${pad(Number(hour))}:${pad(Number(minute))}`;
  if (weekday === "*") return { mode: "daily", time };
  const days = parseWeekdays(weekday);
  return days ? { mode: "weekdays", days, time } : null;
}

/** The guided form for a stored expression, or Custom unless it round-trips exactly. */
export function recognizeSchedule(expression: string): GuidedSchedule {
  const guided = candidate(expression);
  return guided && compileGuided(guided) === expression
    ? guided
    : { mode: "custom" };
}

/** Before the admin picks how often a new scheduler runs: nothing is selected or compiled. */
export type ScheduleChoice = GuidedSchedule | { mode: "unset" };

/**
 * The first view of the schedule fields. A blank (new) form asks the admin to choose a
 * frequency, with no default schedule and no raw cron; a stored expression is recognized
 * (guided on an exact round-trip, else Custom verbatim).
 */
export function initialSchedule(expression: string): ScheduleChoice {
  return expression === "" ? { mode: "unset" } : recognizeSchedule(expression);
}

// ---- preview contract (POST /admin/chat/api/panel/schedulers/preview) ------------------------

export type ScheduleRun = {
  at_utc: string;
  local: string;
  dst_gap: boolean;
  dst_repeat: boolean;
};
export type SchedulePreview = {
  valid: boolean;
  cron_expression: string;
  timezone: { name: string; source: string };
  scheduling: { owner: "this_process" | "separate_worker"; message: string };
  next_runs: ScheduleRun[];
  truncated: boolean;
  warning: { code: string; message: string } | null;
  error: { code: string; message: string; field?: string } | null;
};

export type SchedulePreviewState =
  | { status: "idle" }
  | { status: "loading"; expression: string }
  | { status: "ready"; expression: string; result: SchedulePreview }
  | { status: "failed"; expression: string; error: string };

export type ScheduleSubmitGate = {
  canSubmit: boolean;
  /** Only a new or changed expression is sent; an unchanged one is omitted so it is never rewritten. */
  sendCron: boolean;
  blocker: string | null;
  notice: string | null;
};

/** Whether the form may be saved, for the exact expression in the form. */
export function scheduleSubmitGate(
  storedCron: string | null,
  formCron: string,
  preview: SchedulePreviewState | undefined,
): ScheduleSubmitGate {
  const current =
    preview && preview.status !== "idle" && preview.expression === formCron
      ? preview
      : null;
  if (storedCron !== null && formCron === storedCron) {
    const invalid =
      current?.status === "ready" && !current.result.valid
        ? current.result.error?.message
        : null;
    return {
      canSubmit: true,
      sendCron: false,
      blocker: null,
      notice: invalid
        ? `The saved schedule is unchanged and not valid: ${invalid} Saving other fields keeps it as it is.`
        : null,
    };
  }
  const blocked = (blocker: string): ScheduleSubmitGate => ({
    canSubmit: false,
    sendCron: true,
    blocker,
    notice: null,
  });
  if (!formCron.trim()) return blocked("Choose how often the action runs.");
  if (!current || current.status === "loading")
    return blocked("Waiting for the next-run preview of this schedule.");
  if (current.status === "failed")
    return blocked(
      "The next-run preview could not be calculated. Retry it before saving.",
    );
  if (!current.result.valid)
    return blocked(
      current.result.error?.message || "This schedule is not valid.",
    );
  return { canSubmit: true, sendCron: true, blocker: null, notice: null };
}

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** "Mon 5 Oct 2026, 09:00 (UTC+02:00)" from the server's local ISO time, independent of the browser zone. */
export function formatRunTime(localIso: string): string {
  const match =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.exec(
      localIso,
    );
  if (!match) return localIso;
  const [, year, month, day, hour, minute, offset] = match;
  const weekday =
    DAY_NAMES[
      new Date(
        Date.UTC(Number(year), Number(month) - 1, Number(day)),
      ).getUTCDay()
    ];
  const zone = offset === "Z" ? "UTC" : `UTC${offset}`;
  return `${weekday} ${Number(day)} ${MONTH_NAMES[Number(month) - 1]} ${year}, ${hour}:${minute} (${zone})`;
}
