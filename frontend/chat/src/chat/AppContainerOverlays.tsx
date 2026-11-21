import { Suspense, lazy } from "react";

import { ArtifactPreviewDrawer } from "./ArtifactPreviewDrawer";

const TraceDrawer = lazy(async () => {
  const module = await import("./traceDrawer");
  return { default: module.TraceDrawer };
});

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

type AppContainerOverlaysProps = any;

export function AppContainerOverlays({
  chatState,
  traceOpen,
  setTraceOpen,
  assistantRetryPromptByMessageId,
  handleRetryFromToolEvent,
  setPreviewArtifact,
  composerDisabled,
  previewArtifact,
  canInspectSetup = false,
}: AppContainerOverlaysProps) {
  return (
    <>
      <Suspense fallback={null}>
        <TraceDrawer
          open={traceOpen}
          events={chatState?.traceEvents ?? []}
          sessionId={chatState?.selectedSession?.id ?? null}
          turnDiff={
            asRecord(
              asRecord(chatState?.selectedThreadContext?.context)?.turn_diff,
            ) ?? null
          }
          routingResolution={
            asRecord(
              asRecord(
                asRecord(chatState?.selectedThreadContext?.context)
                  ?.request_analysis,
              )?.workflow_routing_policy_resolution,
            ) ?? null
          }
          workflowContract={
            asRecord(
              asRecord(
                asRecord(chatState?.selectedThreadContext?.context)
                  ?.request_analysis,
              )?.workflow_contract,
            ) ?? null
          }
          onRetryFromToolEvent={(event: any) => {
            const prompt =
              (event.messageId
                ? assistantRetryPromptByMessageId.get(event.messageId)
                : null) || null;
            if (!prompt) {
              return;
            }
            void handleRetryFromToolEvent(event.id, prompt);
          }}
          onPreviewArtifact={setPreviewArtifact}
          actionsDisabled={composerDisabled}
          canInspectSetup={canInspectSetup}
          onClose={() => setTraceOpen(false)}
        />
      </Suspense>
      <ArtifactPreviewDrawer
        artifact={previewArtifact}
        onClose={() => setPreviewArtifact(null)}
      />
    </>
  );
}
