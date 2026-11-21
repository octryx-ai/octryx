import { useMemo, useState } from "react";

import { GLOBAL_SCOPE, scopeChoices, scopeNames, type ScopeRef } from "./promptCatalogModel";
import type { PromptDetail } from "./promptCatalogTypes";

// The selected version and the scope whose text is shown, with the scopes this user may pick.
export function usePromptDetailScope(detail: PromptDetail | null, initialScope: ScopeRef | null) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [scope, setScope] = useState<ScopeRef>(initialScope ?? GLOBAL_SCOPE);
  const choices = useMemo(
    () => scopeChoices(detail?.writable_scopes, detail?.templates ?? [], initialScope),
    [detail, initialScope],
  );
  const projectNames = useMemo(() => scopeNames(choices), [choices]);
  return { selectedId, setSelectedId, scope, setScope, choices, projectNames };
}
