import { useCallback, useEffect, useRef, useState } from "react";
import type {
  SchedulePreview,
  SchedulePreviewState,
} from "../components/scheduler/scheduleModel";
import { readJson } from "../utils/adminPanelHelpers";

const PREVIEW_URL = "/admin/chat/api/panel/schedulers/preview";

// Replies are tagged with their expression, so a slow answer never stands in for the current input.
export function useSchedulerPreview(
  expression: string,
  enabled: boolean,
  { debounceMs = 300 }: { debounceMs?: number } = {},
) {
  const [preview, setPreview] = useState<SchedulePreviewState>({
    status: "idle",
  });
  const [attempt, setAttempt] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    const request = ++latest.current;
    if (!enabled || !expression.trim()) {
      setPreview({ status: "idle" });
      return undefined;
    }
    setPreview({ status: "loading", expression });
    const controller = new AbortController();
    const timer = setTimeout(() => {
      readJson<SchedulePreview>(PREVIEW_URL, {
        method: "POST",
        body: JSON.stringify({ cron_expression: expression, count: 5 }),
        signal: controller.signal,
      })
        .then((result) => {
          if (latest.current === request)
            setPreview({ status: "ready", expression, result });
        })
        .catch((error: unknown) => {
          if (latest.current !== request) return;
          const message = (error as { message?: unknown } | null)?.message;
          setPreview({
            status: "failed",
            expression,
            error:
              typeof message === "string" && message
                ? message
                : "Request failed",
          });
        });
    }, debounceMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [expression, enabled, attempt, debounceMs]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { preview, retry };
}
