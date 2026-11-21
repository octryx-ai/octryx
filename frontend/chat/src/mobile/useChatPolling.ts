// Polls the mobile chat: every second while a turn runs, every two while the Server answers, else slower.

import { useEffect } from "react";
import type { MobileError } from "./mobileSession";

export function useChatPolling(
  refresh: () => Promise<void>,
  live: boolean,
  waitingOnServer: boolean,
  setError: (error: string) => void,
) {
  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const tick = () => {
      refresh()
        .catch((reason: MobileError) =>
          setError(
            reason.code
              ? reason.code.replace(/_/g, " ")
              : "Could not load the chat.",
          ),
        )
        .finally(() => {
          if (!stopped)
            timer = window.setTimeout(
              tick,
              document.hidden
                ? 15000
                : live
                  ? 1000
                  : waitingOnServer
                    ? 2000
                    : 8000,
            );
        });
    };
    tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [refresh, live, waitingOnServer, setError]);
}
