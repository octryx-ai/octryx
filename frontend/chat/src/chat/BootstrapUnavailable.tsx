import { useEffect, useState } from "react";

import { BOOTSTRAP_RETRY_SECONDS } from "./bootstrapFailure";

type Props = { message: string; onRetry: () => void };

// Shown when the first bootstrap failed: never an empty shell that looks like missing rights. It tries again on its
// own; the first answer that loads replaces it with the app.
export function BootstrapUnavailable({ message, onRetry }: Props) {
  const [seconds, setSeconds] = useState(BOOTSTRAP_RETRY_SECONDS);
  useEffect(() => {
    const timer = window.setInterval(() => {
      setSeconds((left) => {
        if (left > 1) return left - 1;
        onRetry();
        return BOOTSTRAP_RETRY_SECONDS;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [onRetry]);
  return (
    <div className="chat-loading" role="alert" data-testid="bootstrap-unavailable">
      <div>
        <p>{message}</p>
        <p className="admin-panel__muted">Trying again in {seconds} s.</p>
        <button type="button" className="admin-panel__action-btn" onClick={onRetry}>Retry now</button>
      </div>
    </div>
  );
}
