import { ChipSet, FreeList, GroupLabel } from "./BuilderChips";
import { contentAction, isContentPolicy } from "./builderContentModel";
import { actionsWithoutUser, blockState, slug, toggle, usesWho, withField } from "./policyBuilderModel";
import type { BuilderModel } from "./policyBuilderModel";
import type { Catalog, PickerEntities } from "./policyCatalogModel";

export type PaneProps = { model: BuilderModel; onChange: (next: BuilderModel) => void; catalog: Catalog; entities: PickerEntities; required: string[] };

const WHO_MODES: { id: BuilderModel["who"]["mode"]; title: string; text: string }[] = [
  { id: "everyone", title: "Everyone", text: "Every user and agent session" },
  { id: "roles", title: "Roles", text: "Members of platform roles" },
  { id: "groups", title: "Groups", text: "Members of identity groups" },
  { id: "users", title: "Specific users", text: "Named people" },
];

const actionLabels = (catalog: Catalog, actions: string[]) => actions.map((id) => catalog.actions.find((item) => item.id === id)?.label ?? id).join(", ");

// Step 1: name, description, and the @id under Advanced (derived from the name until it is edited).
export function BasicsPane({ model, onChange, idLocked, onIdEdited }: PaneProps & { idLocked: boolean; onIdEdited: () => void }) {
  return (
    <section className="admin-panel__card policies__pane" data-testid="builder-pane-basics">
      <div className="admin-panel__section-header"><span>Basics</span></div>
      <label className="admin-panel__field"><span>Name</span>
        <input value={model.name} maxLength={120} data-testid="builder-name"
          onChange={(event) => onChange({ ...model, name: event.target.value, id: idLocked ? model.id : slug(event.target.value) })} /></label>
      <label className="admin-panel__field"><span>Description</span>
        <textarea rows={2} value={model.description} maxLength={500} data-testid="builder-description" onChange={(event) => onChange({ ...model, description: event.target.value })} /></label>
      <details className="policies__advanced">
        <summary>Advanced</summary>
        <label className="admin-panel__field"><span>Policy id (@id)</span>
          <input value={model.id} maxLength={120} data-testid="builder-id" className="admin-policy-inline-code"
            onChange={(event) => { onIdEdited(); onChange({ ...model, id: event.target.value.trim() }); }} /></label>
      </details>
    </section>
  );
}

// Step 2: who is blocked; who-conditions on checks that do not carry the user are flagged, not hidden.
export function WhoPane({ model, onChange, catalog, entities, required }: PaneProps) {
  const who = model.who;
  const set = (patch: Partial<BuilderModel["who"]>) => onChange({ ...model, who: { ...who, ...patch } });
  const blind = actionsWithoutUser(catalog, model.actions);
  const picker = who.mode === "roles" ? { options: entities.roles.map((item) => item.name), label: (name: string) => { const role = entities.roles.find((item) => item.name === name); return role ? `${name} · ${role.memberCount}` : name; } }
    : who.mode === "groups" ? { options: entities.groups.map((item) => item.name), label: (name: string) => { const group = entities.groups.find((item) => item.name === name); return group ? `${name} · ${group.memberCount}` : name; } }
      : who.mode === "users" ? { options: entities.users.map((item) => item.id), label: (id: string) => entities.users.find((item) => item.id === id)?.name ?? `unknown user ${id}` }
        : null;
  return (
    <section className="admin-panel__card policies__pane" data-testid="builder-pane-who">
      <div className="admin-panel__section-header"><span>Who is blocked</span></div>
      <div className="policies__choice-grid">
        {WHO_MODES.map((mode) => (
          <button key={mode.id} type="button" data-testid={`builder-who-${mode.id}`}
            className={`policies__choice${who.mode === mode.id ? " policies__choice--selected" : ""}`}
            onClick={() => set({ mode: mode.id, items: mode.id === who.mode ? who.items : [] })}>
            <b>{mode.title}</b><span>{mode.text}</span>
          </button>
        ))}
      </div>
      {picker ? (
        <>
          <GroupLabel>{WHO_MODES.find((mode) => mode.id === who.mode)?.title ?? ""}</GroupLabel>
          <ChipSet options={picker.options} selected={who.items} label={picker.label} testId="builder-who-items"
            required={required.includes("who.items")} onToggle={(value) => set({ items: toggle(who.items, value) })} />
        </>
      ) : null}
      <label className="policies__row policies__summary">
        <input type="checkbox" checked={who.except_admins} data-testid="builder-except-admins" onChange={(event) => set({ except_admins: event.target.checked })} />
        Except platform admins
      </label>
      <details className="policies__advanced">
        <summary>Agent session</summary>
        <div className="admin-panel__form-grid">
          <label className="admin-panel__field"><span>Session profile</span>
            <select value={who.session_profile} data-testid="builder-session-profile" onChange={(event) => set({ session_profile: event.target.value })}>
              <option value="">Any profile</option><option value="governed">governed</option><option value="seat">seat</option>
            </select></label>
          <label className="admin-panel__field"><span>Session client</span>
            <input value={who.session_client} placeholder="any client" data-testid="builder-session-client" onChange={(event) => set({ session_client: event.target.value.trim() })} /></label>
        </div>
      </details>
      {usesWho(model) && blind.length ? (
        <div className="policies__warn" data-testid="builder-who-warning">
          Not effective yet for <b>{actionLabels(catalog, blind)}</b>: this check does not carry the user today (it evaluates as User "unknown").
          Role, group and user conditions apply only to coding-agent actions until the user is threaded through.
        </div>
      ) : null}
    </section>
  );
}

// Step 4: where it applies. Classification blocks are disabled with the reason for checks that lack it.
export function WherePane({ model, onChange, catalog, entities, required }: PaneProps) {
  const where = model.where;
  const set = (field: string, value: unknown) => onChange(withField(model, field, value));
  const level = blockState(catalog, "where.classification_at_least", model.actions);
  const connections = blockState(catalog, "where.connection", model.actions);
  const families = model.what.families;
  const usable = entities.namedConnections.filter((item) => !families.length || families.includes(item.connector));
  const workspaceLabel = (id: string) => { const found = entities.workspaces.find((item) => item.id === id); return found ? `${found.name} · ${found.classification || "unclassified"}` : `unknown Workspace ${id}`; };
  const connectionLabel = (id: string) => {
    if (id === "default") return "default · the unnamed default entry";
    const found = entities.namedConnections.find((item) => item.id === id);
    return found ? `${found.name} · ${found.connector} · ${found.scope === "global" ? "Global" : found.workspaceName}` : `unknown connection ${id}`;
  };
  return (
    <section className="admin-panel__card policies__pane" data-testid="builder-pane-where">
      <div className="admin-panel__section-header"><span>Where it applies</span></div>
      {!model.actions.length ? <div className="admin-panel__empty-state">Pick an action first (What).</div> : null}
      <GroupLabel>Workspaces</GroupLabel>
      <ChipSet options={entities.workspaces.map((item) => item.id)} selected={where.workspaces} label={workspaceLabel} testId="builder-workspaces"
        onToggle={(value) => set("where.workspaces", toggle(where.workspaces, value))} />
      <div className="policies__sub">None selected = all Workspaces.</div>
      {level.state !== "hidden" ? (
        <>
          <GroupLabel>Classification at least</GroupLabel>
          <div className="policies__row">
            <select className="admin-users__toolbar-select" value={where.classification_at_least} disabled={level.state === "disabled"} data-testid="builder-level"
              onChange={(event) => set("where.classification_at_least", event.target.value)}>
              <option value="">Any classification</option>
              {catalog.levels.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </div>
          {level.state === "disabled" ? <div className="policies__warn" data-testid="builder-level-disabled">{level.reason}</div> : (
            <details className="policies__advanced">
              <summary>More classification conditions</summary>
              <GroupLabel>Classification is</GroupLabel>
              <ChipSet options={catalog.levels} selected={where.classification_is} testId="builder-level-is"
                onToggle={(value) => set("where.classification_is", toggle(where.classification_is, value))} />
              <label className="policies__row policies__summary">
                <input type="checkbox" checked={where.unclassified} data-testid="builder-unclassified" onChange={(event) => set("where.unclassified", event.target.checked)} />
                Only Workspaces without a resolved classification
              </label>
            </details>
          )}
        </>
      ) : null}
      {connections.state === "available" ? (
        <>
          <GroupLabel>Named connections</GroupLabel>
          <ChipSet options={["default", ...usable.map((item) => item.id)]} selected={where.connections} label={connectionLabel} testId="builder-connections"
            required={required.includes("where.connections")} onToggle={(value) => set("where.connections", toggle(where.connections, value))} />
          <div className="policies__sub">Shown by name, stored by id. None selected = every connection.</div>
        </>
      ) : null}
    </section>
  );
}

// Step 5: the exceptions (unless) and the action-specific switches.
export function ExceptionsPane({ model, onChange, catalog, required }: PaneProps) {
  const cond = model.conditions;
  const set = (field: string, value: unknown) => onChange(withField(model, field, value));
  const shown = (block: string) => blockState(catalog, block, model.actions).state === "available";
  return (
    <section className="admin-panel__card policies__pane" data-testid="builder-pane-exceptions">
      <div className="admin-panel__section-header"><span>Exceptions &amp; conditions</span></div>
      {shown("cond.option_value_missing") ? (
        <>
          <GroupLabel>Unless the command has option value</GroupLabel>
          <FreeList values={cond.unless_option_values} placeholder="--context=<context name>" testId="builder-unless-options"
            required={required.includes("conditions.unless_option_values")} onChange={(next) => set("conditions.unless_option_values", next)} />
          <div className="policies__sub">Matches both "--flag=value" and "--flag value".</div>
        </>
      ) : null}
      {shown("cond.route_is") ? (
        <>
          <GroupLabel>Route is</GroupLabel>
          <select className="admin-users__toolbar-select" value={cond.route} data-testid="builder-route" onChange={(event) => set("conditions.route", event.target.value)}>
            <option value="">Any route</option><option value="seat">seat (the user's own subscription)</option><option value="governed">governed (gateway aliases)</option>
          </select>
        </>
      ) : null}
      {shown("cond.admission_unverified") && !isContentPolicy(model) ? (
        <label className="policies__row policies__summary">
          <input type="checkbox" checked={cond.admission_unverified} data-testid="builder-admission" onChange={(event) => set("conditions.admission_unverified", event.target.checked)} />
          Only when the model admission is not verified
        </label>
      ) : null}
      {shown("cond.seat_mode") ? (
        <>
          <GroupLabel>Workspace seat mode is</GroupLabel>
          <select className="admin-users__toolbar-select" value={cond.seat_mode} data-testid="builder-seat-mode" onChange={(event) => set("conditions.seat_mode", event.target.value)}>
            <option value="">Any seat mode</option><option value="forbidden">forbidden</option><option value="allowed">allowed</option>
          </select>
          <label className="policies__row policies__summary">
            <input type="checkbox" checked={cond.governed_required} data-testid="builder-governed" onChange={(event) => set("conditions.governed_required", event.target.checked)} />
            Only when the Workspace requires governed routing
          </label>
        </>
      ) : null}
      {contentAction(model) ? <div className="policies__sub">The "approved model" exception is part of the outcome and written automatically; it is what lets the changed request pass the second check.</div>
        : model.actions.includes("call_model") ? <div className="policies__sub">Model exceptions are set in "What" (Block every model except …).</div> : null}
      <GroupLabel>People</GroupLabel>
      <div className="policies__sub">"Except platform admins" is set in "Who".</div>
      <div className="policies__note">Need OR across steps or nested logic? Use <b>Advanced → Edit as Cedar</b>. The policy then shows as "Hand-written" and is edited in the Cedar editor from then on.</div>
    </section>
  );
}
