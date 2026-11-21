// The sign-in page of a phone that holds no valid credential: pair it from the Mac, or type the code the pairing
// page shows.

import { useState } from "react";
import type { MobileError } from "./mobileSession";
import { formatClaimInput } from "./mobileDeviceChats";
import { OctryxMark } from "./OctryxMark";

export function ConnectPage({
  onClaim,
}: {
  onClaim: (claim: string) => Promise<void>;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await onClaim(code);
    } catch (reason) {
      setError(
        (reason as MobileError).code === "mobile_rate_limited"
          ? "Too many attempts. Wait a minute."
          : "This code is not valid. Pair again from your Mac.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="m-center">
      <OctryxMark size={56} />
      <h1 className="m-title">Connect to your Mac</h1>
      <ol className="m-steps">
        <li>
          On your Mac, choose <b>Connect iPhone…</b> in the Octryx menu, or run{" "}
          <code>octryx mobile pair</code>.
        </li>
        <li>
          Scan the QR code with the Camera and confirm the number on your Mac.
        </li>
      </ol>
      <form
        className="m-code-form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="m-claim">Code from the pairing page</label>
        <input
          id="m-claim"
          inputMode="text"
          autoCapitalize="characters"
          autoComplete="one-time-code"
          placeholder="XXXX-XXXX"
          value={code}
          onChange={(event) => setCode(formatClaimInput(event.target.value))}
        />
        <button
          type="submit"
          className="m-primary m-full"
          disabled={code.length !== 9 || busy}
        >
          Sign in
        </button>
      </form>
      {error && (
        <p className="m-error" role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
