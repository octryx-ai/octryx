import { useCallback, useEffect, useState } from "react";

import { DataTable } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { StatusLabel } from "../../../layout/StatusLabel";
import { useAdminNavigation } from "../../adminNavigation";
import { loadClientVersion, loadPlatformHealth } from "./platformApi";
import {
  attentionText,
  clientDetails,
  forwardedTrustLabel,
  readClientVersion,
  readPlatformVersion,
  securityLabel,
  serverStateLabel,
  type ClientVersion,
  type PlatformVersion,
} from "./platformVersionModel";

// Admin › Platform › Version: what runs on this installation. The component checks themselves live in
// Operations › Health (one place); this page names how many need attention and links there.

type Row = { key: string; part: string; version: string; state: { label: string; tone: "neutral" | "attention" | "problem" }; note: string;
  noteTitle?: string };

function rowsOf(platform: PlatformVersion, client: ClientVersion): Row[] {
  const rows: Row[] = [{
    key: "server", part: "Octryx server", version: platform.server.version,
    state: serverStateLabel(platform.server.status), note: "",
  }];
  rows.push(client
    ? { key: "client", part: "octryx-claude client", version: client.version, state: { label: "Available", tone: "neutral" },
      note: clientDetails(client), noteTitle: client.sha256 ? `SHA-256 ${client.sha256}` : undefined }
    : { key: "client", part: "octryx-claude client", version: "—", state: { label: "Not available", tone: "attention" }, note: "" });
  return rows;
}

export function PlatformVersionPage() {
  const { openAdminTab } = useAdminNavigation();
  const [platform, setPlatform] = useState<PlatformVersion | null>(null);
  const [client, setClient] = useState<ClientVersion>(null);
  const [problem, setProblem] = useState("");

  const load = useCallback(async () => {
    setProblem("");
    setPlatform(null);
    const [health, clientRaw] = await Promise.allSettled([loadPlatformHealth(), loadClientVersion()]);
    if (health.status === "rejected") {
      setProblem("The version of this installation could not be read.");
      return;
    }
    setPlatform(readPlatformVersion(health.value));
    setClient(clientRaw.status === "fulfilled" ? readClientVersion(clientRaw.value) : null);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (problem) {
    return <EmptyLine text={problem} action={{ label: "Try again", onClick: () => void load() }} testId="platform-version-error" />;
  }
  const attention = platform ? attentionText(platform.server.attention) : "";
  const security = platform?.security ?? null;
  return (
    <section className="platform-page" data-testid="platform-version">
      <DataTable<Row>
        label="Installed parts"
        testId="platform-version-table"
        loading={platform === null}
        loadingLabel="version"
        onRetry={() => void load()}
        rows={platform ? rowsOf(platform, client) : []}
        rowKey={(row) => row.key}
        columns={[
          { key: "part", header: "Part", grow: true, render: (row) => row.part },
          { key: "version", header: "Version", nowrap: true, render: (row) => row.version },
          { key: "state", header: "State", nowrap: true, render: (row) => <StatusLabel label={row.state.label} tone={row.state.tone} /> },
          // A column with a header, on one line (the checksum was squeezed into a headerless column).
          { key: "note", header: "Details", nowrap: true, render: (row) => <span title={row.noteTitle}>{row.note}</span> },
        ]}
      />
      {attention ? (
        <EmptyLine text={attention} action={{ label: "Open Health", onClick: () => openAdminTab("observabilityHealth") }}
          testId="platform-version-attention" />
      ) : null}
      {security ? (
        <dl className="platform-facts" data-testid="platform-version-security">
          <div><dt>Security defaults</dt><dd>
            <StatusLabel label={securityLabel(security.status).label} tone={securityLabel(security.status).tone} />
          </dd></div>
          <div><dt>Runtime profile</dt><dd>{security.runtimeProfile}{security.productionLike ? " · production-like" : ""}</dd></div>
          <div><dt>Debug</dt><dd>{security.debug ? "On" : "Off"}</dd></div>
          <div><dt>Secure sign-in cookies</dt><dd>{security.secureCookies ? "Forced" : "Not forced"}</dd></div>
          <div><dt>Forwarded headers</dt><dd>{forwardedTrustLabel(security.forwardedHeaderTrust)}</dd></div>
        </dl>
      ) : null}
    </section>
  );
}
