import { SidePanel } from "../../../layout/SidePanel";
import { InboundSecretFields } from "./InboundSecretFields";
import { InboundCreateFooter, InboundCreateForm } from "./InboundWebhookCreateFields";
import type { ActionOption, InboundSource, InboundWebhook } from "./inboundWebhookModel";
import { useInboundWebhookCreate, type ReadJson } from "./useInboundWebhookCreate";

type Props = {
  sources: InboundSource[];
  projects: { id: string; name: string }[];
  actions: ActionOption[];
  readJson: ReadJson;
  onCreated: (webhook: InboundWebhook) => void;
  onOpen: (webhookId: string) => void;
  onClose: () => void;
};

// One short form in a side panel: source, name, Workspace, the action it starts.
// Filters, repeat grouping and limits have safe defaults and are changed later in the drawer. After create: URL + secret once, then "test".
export function InboundWebhookCreateDrawer({
  sources,
  projects,
  actions,
  readJson,
  onCreated,
  onOpen,
  onClose,
}: Props) {
  const form = useInboundWebhookCreate({ sources, actions, readJson, onCreated });
  const { created } = form;

  return (
    <SidePanel
      title={created ? created.name : "New webhook"}
      subtitle="Inbound webhook"
      onClose={onClose}
      footer={<InboundCreateFooter form={form} onClose={onClose} onOpen={onOpen} />}
      testId="inbound-webhook-create"
    >
      {created ? (
        <div className="automation-page">
          <div className="automation-okbox">
            Webhook created. Paste the URL and the secret into the sending tool,
            then send a test.
          </div>
          <InboundSecretFields webhook={created} />
        </div>
      ) : (
        <InboundCreateForm form={form} sources={sources} projects={projects} onClose={onClose} />
      )}
    </SidePanel>
  );
}
