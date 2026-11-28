import { RuntimeExecutionSection } from "./runtimeTab/RuntimeExecutionSection";
import type { RuntimeTabCtx } from "./runtimeTab/types";

type RuntimeSection = "execution";

type AdminRuntimesTabProps = {
  ctx: Record<string, unknown>;
  section: RuntimeSection;
};

export function AdminRuntimesTab({ ctx, section }: AdminRuntimesTabProps) {
  return <RuntimeSectionPage ctx={ctx as RuntimeTabCtx} section={section} />;
}

function RuntimeSectionPage({ ctx, section }: { ctx: RuntimeTabCtx; section: RuntimeSection }) {
  return (
    <div>
      <RuntimeSectionBody ctx={ctx} section={section} />
    </div>
  );
}

function RuntimeSectionBody({ ctx, section }: { ctx: RuntimeTabCtx; section: RuntimeSection }) {
  switch (section) {
    case "execution": return <RuntimeExecutionSection ctx={ctx} />;
    default: return null;
  }
}
