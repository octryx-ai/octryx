// Cron helper for the scheduler form. Behaviour source:
// backend/app/scheduler/dispatch/registration.py uses APScheduler 3
// CronTrigger.from_crontab on an AsyncIOScheduler without an explicit time zone.
// In APScheduler the numeric weekday counts from Monday = 0 (standard cron uses
// Sunday = 0), so the examples use weekday names, which mean the same in both.

const CRON_EXAMPLES = [
  { expression: "*/15 * * * *", meaning: "every 15 minutes" },
  { expression: "0 2 * * *", meaning: "every day at 02:00" },
  { expression: "0 9 * * mon-fri", meaning: "weekdays at 09:00" },
  { expression: "30 7 1 * *", meaning: "07:30 on the 1st of every month" },
];

export function AdminSchedulerCronHelp() {
  return (
    <div className="admin-form-help" id="scheduler-cron-help">
      Five fields: minute, hour, day of month, month, day of week. The next-run
      preview names the time zone the times are calculated in.
      <ul className="admin-scheduler__cron-examples">
        {CRON_EXAMPLES.map((example) => (
          <li key={example.expression}>
            <code>{example.expression}</code> — {example.meaning}
          </li>
        ))}
      </ul>
      Write weekdays as names (<code>mon</code>–<code>sun</code>): numbers count
      from Monday = 0 here, unlike standard cron.
    </div>
  );
}
