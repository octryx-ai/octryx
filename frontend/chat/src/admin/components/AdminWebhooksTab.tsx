import { useState } from "react";

import "./automation/automationPages.css";
import "./adminChannels.css";
import { SegmentedTabs } from "../../layout/SegmentedTabs";
import { InboundWebhooksPage } from "./inboundWebhooks/InboundWebhooksPage";
import { AdminOutboundDeliverySection } from "./AdminOutboundDeliverySection";
import { AdminOutboundWebhooksSection } from "./AdminOutboundWebhooksSection";
import type { AdminWebhooksTabProps } from "./webhookTypes";

type AdminWebhooksTabWrapperProps = {
  ctx: Record<string, unknown>;
};

export function AdminWebhooksTab({ ctx }: AdminWebhooksTabWrapperProps) {
  const props = ctx as AdminWebhooksTabProps;
  const [view, setView] = useState<"inbound" | "outbound">("inbound");

  // Inbound (an alert starts an analysis) and Outbound (send events) as two views of one page, in the
  // one segmented tab style.
  return (
    <div className="automation-page">
      <SegmentedTabs
        label="Webhook direction"
        size="small"
        idPrefix="webhooks-direction"
        testId="webhooks-direction"
        value={view}
        onChange={(key) => setView(key as "inbound" | "outbound")}
        tabs={[
          { key: "inbound", label: "Inbound" },
          { key: "outbound", label: "Outbound" },
        ]}
      />
      {view === "inbound" ? (
        <InboundWebhooksPage
          projects={props.projects}
          readJson={props.readJson}
        />
      ) : null}
      {view === "outbound" ? (
        <>
          <AdminOutboundWebhooksSection
            projects={props.projects}
            outboundWebhooks={props.outboundWebhooks}
            showCreateOutboundWebhook={props.showCreateOutboundWebhook}
            setShowCreateOutboundWebhook={props.setShowCreateOutboundWebhook}
            editingOutboundWebhookId={props.editingOutboundWebhookId}
            setEditingOutboundWebhookId={props.setEditingOutboundWebhookId}
            outboundWebhookFormName={props.outboundWebhookFormName}
            setOutboundWebhookFormName={props.setOutboundWebhookFormName}
            outboundWebhookFormUrl={props.outboundWebhookFormUrl}
            setOutboundWebhookFormUrl={props.setOutboundWebhookFormUrl}
            outboundWebhookFormProjectId={props.outboundWebhookFormProjectId}
            setOutboundWebhookFormProjectId={
              props.setOutboundWebhookFormProjectId
            }
            outboundWebhookFormEvents={props.outboundWebhookFormEvents}
            setOutboundWebhookFormEvents={props.setOutboundWebhookFormEvents}
            outboundWebhookFormLoading={props.outboundWebhookFormLoading}
            setOutboundWebhookFormLoading={props.setOutboundWebhookFormLoading}
            outboundWebhookFormError={props.outboundWebhookFormError}
            setOutboundWebhookFormError={props.setOutboundWebhookFormError}
            createdOutboundSigningSecret={props.createdOutboundSigningSecret}
            setCreatedOutboundSigningSecret={
              props.setCreatedOutboundSigningSecret
            }
            outboundWebhookEventOptions={props.outboundWebhookEventOptions}
            readJson={props.readJson}
            reloadWebhooksTab={props.reloadWebhooksTab}
          />

          <AdminOutboundDeliverySection
            totalCount={props.outboundWebhookDeliveries.length}
            visible={props.showOutboundDeliveries}
            setVisible={props.setShowOutboundDeliveries}
            search={props.outboundWebhookDeliverySearch}
            setSearch={props.setOutboundWebhookDeliverySearch}
            deliveries={props.outboundWebhookDeliveries}
            filteredDeliveries={props.filteredOutboundWebhookDeliveries}
            formatDateTime={props.formatDateTime}
          />
        </>
      ) : null}
    </div>
  );
}
