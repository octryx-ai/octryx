import { useState } from "react";
import type { ReactNode } from "react";

import { authModeLabel, connectionTarget, lastTestText, storedSecretsText, usageLines } from "./namedConnectionsText";
import { boundScopesFact, inheritedServesText } from "./namedConnectionsForm";
import type { NamedConnection, NamedConnector } from "./namedConnectionsTypes";

type Props = {
  connection: NamedConnection;
  connector: NamedConnector;
  // Inherited (global) connections in a Workspace: the keys served here and the ones the Workspace overrides.
  inherited?: boolean;
  children?: ReactNode;
};

// The connection's id never changes and is what other configuration references (a Knowledge connector's pinned
// connection, run reports, audit), so it can be copied. The raw id is not shown on screen:
// it is the Copy ID button's tooltip (and read by assistive technology).
function CopyId({ id }: { id: string }) {
  const [copied, setCopied] = useState<boolean | null>(null);
  const copy = async () => {
    const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
    try {
      if (!clipboard) throw new Error("no clipboard");
      await clipboard.writeText(id);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <span className="named-connections__id">
      <span className="ds-sr-only">ID <code data-testid="named-connection-id">{id}</code></span>
      <button type="button" className="admin-panel__action-btn" aria-label={`Copy the id ${id}`} title={id}
        onClick={() => void copy()}>
        {copied === true ? "Copied" : "Copy ID"}
      </button>
      {copied === false ? <span className="admin-panel__muted"> Copy is not available here; select the id.</span> : null}
    </span>
  );
}

// One named connection, read-only: id, name, target, sign-in, bound keys, secret presence (never a value), last
// test and who uses it. Actions (edit, test, delete) come in as children.
export function NamedConnectionDetails({ connection, connector, inherited = false, children }: Props) {
  const users = usageLines(connection.usage, connector);
  const target = connectionTarget(connector, connection.publicFields);
  return (
    <>
      <div className="named-connections__head">
        <strong>{connection.name}</strong>
        {inherited ? <span className="admin-panel__muted"> · global, read-only</span> : null}
        <CopyId id={connection.id} />
      </div>
      <div className="named-connections__facts" data-testid="named-connection-facts">
        {[
          target ?? "No URL set",
          authModeLabel(connector, connection.publicFields),
          boundScopesFact(connection, connector),
          storedSecretsText(connection),
        ].join(" · ")}
        {" · "}
        <span className={connection.lastTest && !connection.lastTest.ok ? "named-connections__failed" : undefined}>
          {lastTestText(connection.lastTest)}
        </span>
      </div>
      {inherited ? (
        <div className="admin-panel__hint" data-testid="named-connection-inherited">
          {inheritedServesText(connection, connector)}
        </div>
      ) : null}
      {connection.usage ? (
        <div className="admin-panel__hint" data-testid="named-connection-usage">
          {users.length ? `Used by: ${users.join("; ")}.` : "Not used by any Workspace or Knowledge connector."}
        </div>
      ) : null}
      {children}
    </>
  );
}
