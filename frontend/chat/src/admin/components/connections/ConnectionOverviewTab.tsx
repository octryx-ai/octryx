// The Overview tab of one connection: the last test's checks, its name and facts, access, where it is available and,
// for a bound type, the keys it serves.
import { TimeText } from "../../utils/TimeText";
import { FormSection } from "../../../layout/FormSection";
import { StatusLabel } from "../../../layout/StatusLabel";
import { BoundScopesEditor } from "./BoundScopesEditor";
import { AccessFields, AvailableInEditor, Field, type FieldErrors } from "./ConnectionFields";
import type { UnboundToday } from "./boundScopes";
import type { ConnectionDraft } from "./connectionDraft";
import { authLabel, findType, typeLabel, type accessFieldsOf, type Binding, type ConnectionType } from "./connectionTypes";
import type { ConnectionDetail, TestResult, WorkspaceRef } from "./connectionsModel";
import { effectiveAuthKind } from "./authFields";

type Props = {
  detail: ConnectionDetail;
  draft: ConnectionDraft;
  setDraft: (patch: Partial<ConnectionDraft>) => void;
  types: ConnectionType[];
  workspaces: WorkspaceRef[];
  fields: ReturnType<typeof accessFieldsOf>;
  binding: Binding | null;
  bindingEditable: boolean;
  readOnly: boolean;
  errors: FieldErrors;
  testResult: TestResult | null;
  isAdmin: boolean;
  onOpenConnectorSettings?: (type: string) => void;
  setUnboundToday: (today: UnboundToday | null) => void;
};

function TestChecks({ testResult }: { testResult: TestResult }) {
  return (
    <ul className="connections__checks" data-testid="connection-test-checks">
      {testResult.checks.map((check) => (
        <li key={check.use}><StatusLabel label={check.ok ? "Passed" : "Failed"} />{` ${check.use}${check.message ? `: ${check.message}` : ""}`}</li>
      ))}
    </ul>
  );
}

export function ConnectionOverviewTab({
  detail, draft, setDraft, types, workspaces, fields, binding, bindingEditable, readOnly, errors, testResult, isAdmin,
  onOpenConnectorSettings, setUnboundToday,
}: Props) {
  return (
    <div className="connections__tab" data-testid="connection-tab-overview">
      {testResult ? <TestChecks testResult={testResult} /> : null}
      {readOnly ? <p className="connections__fact" data-testid="connection-read-only">Managed by the platform; you can read it.</p> : null}
      <FormSection title="Connection">
        <Field label="Name" path="name" errors={errors}>
          <input className="admin-panel__input" value={draft.name} disabled={readOnly} onChange={(event) => setDraft({ name: event.target.value })} />
        </Field>
        <p className="connections__fact">Type: {typeLabel(detail.type, types)} · Sign-in: {authLabel(effectiveAuthKind(detail.type, detail.access.auth, draft.access))}
          {detail.lastTestedAt ? <> · tested <TimeText value={detail.lastTestedAt} mode="recent" /></> : " · not tested yet"}</p>
      </FormSection>
      <FormSection title="Access">
        <AccessFields fields={fields} descriptor={findType(types, detail.type)}
          value={{ values: draft.access, secrets: draft.secrets }} stored={detail.access.secrets}
          readOnly={readOnly} errors={errors}
          onChange={(next) => setDraft({ access: next.values, secrets: next.secrets })} />
      </FormSection>
      <FormSection title="Available in">
        <AvailableInEditor availableIn={draft.availableIn} workspaceIds={draft.workspaceIds} workspaces={workspaces}
          readOnly={readOnly} errors={errors} onChange={(next) => setDraft(next)} />
      </FormSection>
      {binding ? (
        <FormSection title={binding.plural}>
          <BoundScopesEditor binding={binding} value={draft.boundScopes} saved={detail.boundScopes} editable={bindingEditable}
            errors={errors} isAdmin={isAdmin} type={detail.type} onChange={(text) => setDraft({ boundScopes: text })}
            workspaces={detail.availableIn === "all" ? workspaces : detail.workspaces}
            onOpenConnectorSettings={onOpenConnectorSettings} onToday={setUnboundToday} />
        </FormSection>
      ) : null}
    </div>
  );
}
