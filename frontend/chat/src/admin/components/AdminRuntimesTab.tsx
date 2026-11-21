import { RuntimeCompressionSection } from "./runtimeTab/RuntimeCompressionSection";
import { RuntimeExecutionSection } from "./runtimeTab/RuntimeExecutionSection";
import { RuntimeEvidenceGroundingSection } from "./runtimeTab/RuntimeEvidenceGroundingSection";
import type { RuntimeTabCtx } from "./runtimeTab/types";

// The Runtime sections owned here: execution and compression. Model priority, defaults, routing and fallback are
// Runtime → Default & fallback (modelSelection/AdminDefaultAndFallback); Limits & budgets is
// limits/AdminLimitsAndBudgets.
type RuntimeSection = "execution" | "compression";

type AdminRuntimesTabProps = {
  ctx: Record<string, unknown>;
  // Set by the area navigation: each register is its own page.
  section: RuntimeSection;
};

export function AdminRuntimesTab({ ctx, section }: AdminRuntimesTabProps) {
  return <RuntimeSectionPage ctx={ctx as RuntimeTabCtx} section={section} />;
}

// No description line on the page: what each page decides is in help/admin/<page>.md.
function RuntimeSectionPage({ ctx, section }: { ctx: RuntimeTabCtx; section: RuntimeSection }) {
  return (
    <div>
      <RuntimeSectionBody ctx={ctx} section={section} />
    </div>
  );
}

function RuntimeSectionBody({ ctx, section }: { ctx: RuntimeTabCtx; section: RuntimeSection }) {
  switch (section) {
    case "execution": return <><RuntimeExecutionSection ctx={ctx} /><RuntimeEvidenceGroundingSection /></>;
    case "compression": return <RuntimeCompressionSection ctx={ctx} />;
    default: return null;
  }
}
