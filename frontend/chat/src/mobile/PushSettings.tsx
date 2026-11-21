// Octryx Mobile: notifications on this phone (Web Push through Apple's push service). iOS offers push only
// to a Home Screen app, and asks for permission only after a tap, so turning it on is a button here.

import { useEffect, useState } from "react";
import {
  deletePush,
  loadPush,
  savePush,
  type PushRules,
  type PushState,
} from "./mobileApi";
import { applicationServerKey, pushSupport } from "./mobilePush";

const GROUPS: { key: keyof PushRules; label: string; hint: string }[] = [
  {
    key: "needs_you",
    label: "Needs you",
    hint: "Approvals, questions, seat and budget limits",
  },
  // Run and device problems (activity problems) arrive through this group as push.
  { key: "problem", label: "Problems", hint: "Your runs and device jobs that are stuck or failed" },
  { key: "done", label: "Done", hint: "Finished work" },
];

async function subscribeHere(publicKey: string): Promise<PushSubscription> {
  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  if (existing) return existing;
  return registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: applicationServerKey(publicKey),
  });
}

function PushSwitches({ state, busy, turnOff, toggle }: {
  state: PushState;
  busy: boolean;
  turnOff: () => Promise<void>;
  toggle: (key: keyof PushRules) => unknown;
}) {
  return (
    <>
      <ul className="m-switches">
        {GROUPS.map((group) => (
          <li key={group.key}>
            <label>
              <span>
                <strong>{group.label}</strong>
                <small>{group.hint}</small>
              </span>
              <input
                type="checkbox"
                role="switch"
                checked={state.rules[group.key]}
                disabled={busy}
                onChange={() => void toggle(group.key)}
              />
            </label>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="m-secondary m-full"
        disabled={busy}
        onClick={() => void turnOff()}
      >
        Turn off notifications
      </button>
    </>
  );
}

// What the section shows: loading, why notifications are not possible here, the button to turn them on, or the switches.
function PushBody({ state, error, support, busy, turnOn, turnOff, toggle }: {
  state: PushState | null;
  error: string;
  support: ReturnType<typeof pushSupport>;
  busy: boolean;
  turnOn: () => Promise<void>;
  turnOff: () => Promise<void>;
  toggle: (key: keyof PushRules) => unknown;
}) {
  if (!state) {
    return <p className="m-muted">{error || "Loading…"}</p>;
  } else if (!state.configured) {
    return (
      <p className="m-muted">
        Notifications are not set up on this platform yet.
      </p>
    );
  } else if (support === "home-screen") {
    return (
      <p className="m-muted">
        Add Octryx to your Home Screen first (Share, then Add to Home Screen),
        and open it from there.
      </p>
    );
  } else if (support === "unsupported") {
    return <p className="m-muted">This browser cannot show notifications.</p>;
  } else if (!state.subscribed) {
    return (
      <button
        type="button"
        className="m-primary m-full"
        disabled={busy}
        onClick={() => void turnOn()}
      >
        Turn on notifications
      </button>
    );
  }
  return <PushSwitches state={state} busy={busy} turnOff={turnOff} toggle={toggle} />;
}

// Asks for permission, subscribes this phone and saves the subscription with the current rules.
async function turnOnHere(state: PushState | null) {
  const permission = await Notification.requestPermission();
  if (permission !== "granted")
    throw Object.assign(new Error("denied"), { name: "NotAllowedError" });
  const subscription = await subscribeHere(state?.public_key ?? "");
  return savePush({
    subscription: subscription.toJSON(),
    rules: state?.rules,
  });
}

async function turnOffHere() {
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  await subscription?.unsubscribe().catch(() => false);
  return deletePush();
}

export function PushSettings() {
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const support = pushSupport(window, navigator);

  useEffect(() => {
    loadPush().then(setState, () =>
      setError("Notification settings could not be loaded."),
    );
  }, []);

  const run = async (work: () => Promise<PushState>) => {
    setBusy(true);
    setError("");
    try {
      setState(await work());
    } catch (reason) {
      const name = (reason as Error).name;
      setError(
        name === "NotAllowedError"
          ? "Notifications are blocked. Allow them for Octryx in the iPhone's Settings."
          : "That did not work. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const turnOn = () => run(() => turnOnHere(state));

  const turnOff = () => run(turnOffHere);

  const toggle = (key: keyof PushRules) =>
    state &&
    run(() =>
      savePush({ rules: { ...state.rules, [key]: !state.rules[key] } }),
    );

  const body = (
    <PushBody state={state} error={error} support={support} busy={busy} turnOn={turnOn} turnOff={turnOff} toggle={toggle} />
  );
  return (
    <section className="m-push" aria-labelledby="m-push-title">
      <h2 id="m-push-title" className="m-section">
        Notifications
      </h2>
      {body}
      {error && state && (
        <p className="m-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
