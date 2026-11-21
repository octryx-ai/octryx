import { useState } from "react";
import { pageTreeToAdd, readPageAddress, type PageAddress } from "./confluencePageTree";
import type { FormState } from "./connectorFormModel";

const OPTION_LABEL = { display: "flex", alignItems: "center", gap: "0.35rem" } as const;

type Props = {
  form: FormState;
  set: (patch: Partial<FormState>) => void;
  /** The whole-space input and its help (shared with the Jira project keys input). */
  spaceKeysInput: JSX.Element;
};

// A Confluence connector's scope: whole spaces, or page trees (a root page and every page below it). A pasted page
// address is read here and its space key and page id are shown; only "Add page tree" adds them, and the pasted
// text is never rewritten. Whole spaces may be kept next to trees in other spaces.
export function KnowledgeConfluenceScopeFields({ form, set, spaceKeysInput }: Props) {
  const [address, setAddress] = useState("");
  const [typedSpace, setTypedSpace] = useState("");
  const read = readPageAddress(address);
  const toAdd = pageTreeToAdd(read, typedSpace);
  const duplicate =
    toAdd && "tree" in toAdd
      ? form.pageTrees.some((tree) => tree.root_page_id === toAdd.tree.root_page_id)
      : false;
  const add = () => {
    if (!toAdd || !("tree" in toAdd) || duplicate) return;
    set({ pageTrees: [...form.pageTrees, toAdd.tree] });
    setAddress("");
    setTypedSpace("");
  };
  const remove = (rootPageId: string) =>
    set({ pageTrees: form.pageTrees.filter((tree) => tree.root_page_id !== rootPageId) });

  return (
    <>
      <ScopeModeChoice form={form} set={set} />

      {form.scopeMode === "spaces" ? (
        <>
          {spaceKeysInput}
          {form.pageTrees.length ? (
            <div className="admin-panel__hint" role="note" style={{ margin: 0 }} data-testid="page-trees-dropped">
              Saving with whole spaces removes the {form.pageTrees.length} page tree
              {form.pageTrees.length === 1 ? "" : "s"} of this connector.
            </div>
          ) : null}
        </>
      ) : (
        <>
          <PageTreeList trees={form.pageTrees} onRemove={remove} />
          <input className="admin-panel__input" aria-label="Root page address" value={address}
            placeholder="Root page address: https://<site>/wiki/spaces/<SPACE>/pages/<page id>/<title>"
            onChange={(event) => setAddress(event.target.value)} />
          {read.kind === "problem" ? (
            <div className="admin-panel__hint" role="note" style={{ margin: 0 }} data-testid="page-address-problem">
              {read.text}
            </div>
          ) : null}
          {read.kind === "page" ? (
            <PageAddressRead read={read} typedSpace={typedSpace} onTypedSpace={setTypedSpace} toAdd={toAdd} duplicate={duplicate} onAdd={add} />
          ) : null}
          <input className="admin-panel__input" aria-label="Whole spaces too" value={form.keys}
            placeholder="Also sync whole spaces (optional): SPACE1, SPACE2"
            onChange={(event) => set({ keys: event.target.value })} />
        </>
      )}
    </>
  );
}

function PageTreeList({ trees, onRemove }: { trees: FormState["pageTrees"]; onRemove: (rootPageId: string) => void }) {
  return trees.length ? (
    <ul className="admin-panel__stack admin-panel__stack--compact" style={{ margin: 0, paddingLeft: "1.1rem" }}
      data-testid="page-tree-list">
      {trees.map((tree) => (
        <li key={tree.root_page_id}>
          Space <code>{tree.space_key}</code> · root page <code>{tree.root_page_id}</code> and every page below it{" "}
          <button type="button" className="admin-panel__action-btn" onClick={() => onRemove(tree.root_page_id)}
            aria-label={`Remove page tree ${tree.root_page_id}`}>
            Remove
          </button>
        </li>
      ))}
    </ul>
  ) : (
    <div className="admin-panel__hint" style={{ margin: 0 }}>No page tree yet: paste the address of a root page.</div>
  );
}

// What was read from a pasted page address, the space key when the address does not show it, and "Add page tree".
function PageAddressRead({ read, typedSpace, onTypedSpace, toAdd, duplicate, onAdd }: {
  read: Extract<PageAddress, { kind: "page" }>;
  typedSpace: string;
  onTypedSpace: (value: string) => void;
  toAdd: ReturnType<typeof pageTreeToAdd>;
  duplicate: boolean;
  onAdd: () => void;
}) {
  return (
    <div className="admin-panel__stack admin-panel__stack--compact" data-testid="page-address-read">
      <div className="admin-panel__hint" style={{ margin: 0 }}>
        Read from the address: page id <code>{read.rootPageId}</code>
        {read.spaceKey ? <> in space <code>{read.spaceKey}</code></> : <>; the address does not show the space</>}.
        Check them, then add the tree.
      </div>
      {read.spaceKey ? null : (
        <input className="admin-panel__input" aria-label="Space key of the page" value={typedSpace}
          placeholder="Space key of the page" onChange={(event) => onTypedSpace(event.target.value)} />
      )}
      {toAdd && "problem" in toAdd ? (
        <div className="admin-panel__hint" role="note" style={{ margin: 0 }}>{toAdd.problem}</div>
      ) : null}
      {duplicate ? (
        <div className="admin-panel__hint" role="note" style={{ margin: 0 }}>This root page is already listed.</div>
      ) : null}
      <div>
        <button type="button" className="admin-panel__action-btn"
          disabled={!toAdd || !("tree" in toAdd) || duplicate} onClick={onAdd}>
          Add page tree
        </button>
      </div>
    </div>
  );
}

function ScopeModeChoice({ form, set }: Pick<Props, "form" | "set">) {
  return (
    <div role="radiogroup" aria-label="Confluence scope" style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
      <label className="admin-panel__muted" style={OPTION_LABEL}>
        <input type="radio" name="confluence-scope" value="spaces" checked={form.scopeMode === "spaces"}
          onChange={() => set({ scopeMode: "spaces" })} />
        Whole spaces
      </label>
      <label className="admin-panel__muted" style={OPTION_LABEL}>
        <input type="radio" name="confluence-scope" value="trees" checked={form.scopeMode === "trees"}
          onChange={() => set({ scopeMode: "trees" })} />
        Page trees (a page and every page below it)
      </label>
    </div>
  );
}
