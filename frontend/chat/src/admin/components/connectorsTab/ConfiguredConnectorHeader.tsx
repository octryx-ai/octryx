import type { ReactNode } from "react";
import { useAdminNavigation } from "../../adminNavigation";
import { openPolicies } from "../policyEngine/policyLinks";
import { usePolicyReferences } from "../policyEngine/usePolicyReferences";
import {
  configuredConnectorStatus,
  connectionTestAvailable,
} from "./configuredConnectorStatus";
import "./configuredConnectorStatus.css";
import "../automation/automationPages.css";

type ConfiguredConnectorHeaderProps = {
  connector: any;
  health: any;
  iconColor: string;
  isOpen: boolean;
  ctx: Record<string, unknown>;
};

/** The connector's icon (or its first letter), name and tool count. */
function ConnectorCardHead({ connector, iconColor, icon }: { connector: any; iconColor: string; icon: ReactNode }) {
  return (
    <div className="automation-card__head">
      <div className="connector-card__icon" style={{ background: iconColor }}>
        {icon ?? (
          <span className="connector-card__icon-fallback">
            {connector.label[0]}
          </span>
        )}
      </div>
      <div className="automation-card__titles">
        <div className="automation-card__name">{connector.label}</div>
        <div className="automation-card__sub">
          {connector.tools.length} tool
          {connector.tools.length === 1 ? "" : "s"}
        </div>
      </div>
    </div>
  );
}

/** The health badge and, when platform policies name the connector, the policies badge that opens them. */
function ConnectorCardBadges({ badgeClass, badgeText, policies, onPolicies }: {
  badgeClass: string;
  badgeText: ReactNode;
  policies: number;
  onPolicies: () => void;
}) {
  return (
    <div className="automation-card__badges">
      <span
        className={`connector-card__meta-badge ${badgeClass}`}
        data-testid="connector-health-badge"
      >
        {badgeText}
      </span>
      {policies ? (
        <button
          type="button"
          className="connector-card__meta-badge"
          data-testid="connector-policies-badge"
          title="Open the platform policies that name this connector"
          onClick={(event) => {
            event.stopPropagation();
            onPolicies();
          }}
        >
          {policies} polic{policies === 1 ? "y" : "ies"}
        </button>
      ) : null}
    </div>
  );
}

/** When the connection was last checked (or why it never was), with the check's error when the status lacks it. */
function ConnectorCardFoot({ connector, checked, error }: { connector: any; checked: string; error: string }) {
  return (
    <div className="automation-card__foot">
      <span>
        {checked
          ? `Checked ${checked}`
          : connector.configured
            ? "Not checked yet"
            : connector.workspace_connections
              ? "No global connection"
              : "Not configured"}
        {error ? ` · ${error}` : ""}
      </span>
    </div>
  );
}

export function ConfiguredConnectorHeader({ connector, health, iconColor, isOpen, ctx }: ConfiguredConnectorHeaderProps) {
  const {
    CONNECTOR_ICONS,
    connectorHealthStatusClass,
    formatConnectorHealthStatus,
    formatRelativeTime,
    handleExpandConnector,
  } = ctx as Record<string, any>;
  // U1: "Connected" only with a successful health check; a failing one shows its problem instead.
  const status = configuredConnectorStatus(connector, health);
  // An untestable preset's recorded "error" is not a health problem: a muted "No test" badge instead.
  const testable = connectionTestAvailable(connector, health);
  // Policy UX: how many platform policies name this connector (platform admins; nothing for others).
  const { openAdminTab } = useAdminNavigation();
  const policies =
    usePolicyReferences()?.connectors[connector.tool_name]?.count ?? 0;

  const checked = health?.last_checked
    ? formatRelativeTime(health.last_checked)
    : "";
  const open = () => handleExpandConnector(connector.tool_name, connector);

  // A grid card. Status in words, no latency figure, no lone Remove button: removal and pause
  // live in the drawer that the card opens.
  return (
    <div
      className="automation-card connector-grid-card"
      role="button"
      tabIndex={0}
      aria-expanded={isOpen}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      }}
    >
      <ConnectorCardHead connector={connector} iconColor={iconColor} icon={CONNECTOR_ICONS[connector.tool_name]} />
      <ConnectorCardBadges
        badgeClass={testable ? connectorHealthStatusClass(health?.status) : "connector-card__meta-badge--muted"}
        badgeText={testable ? formatConnectorHealthStatus(health?.status) : "No test"}
        policies={policies}
        onPolicies={() => openPolicies(openAdminTab, { connector: connector.tool_name })}
      />
      <div
        className={`connector-card__status${status.tone === "neutral" ? "" : ` connector-card__status--${status.tone}`}`}
        data-testid="connector-status"
      >
        {status.text}
      </div>
      <ConnectorCardFoot connector={connector} checked={checked} error={health?.error && !status.errorInStatus ? health.error : ""} />
    </div>
  );
}
