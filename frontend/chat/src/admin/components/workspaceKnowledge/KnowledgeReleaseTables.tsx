import { Fragment } from "react";
import { FieldError, ReleaseTagList } from "./KnowledgeReleaseTags";
import { errorsFor, moveRow, newProductRow, newSectionRow } from "./jiraReleasesModel";
import type { FieldErrors, ProductRow, SectionRow } from "./jiraReleasesModel";

const inputClass = (invalid: boolean) => `admin-panel__form-input${invalid ? " kr-input--error" : ""}`;

// Jira project key -> product. The project must be one of the connector's project keys (offered as suggestions;
// the server decides). One product per project.
export function ReleaseProductsTable({ rows, projectKeys, errors, onChange }: {
  rows: ProductRow[];
  projectKeys: string[];
  errors: FieldErrors;
  onChange: (rows: ProductRow[]) => void;
}) {
  const update = (index: number, patch: Partial<ProductRow>) =>
    onChange(rows.map((row, other) => (other === index ? { ...row, ...patch } : row)));
  return (
    <>
      {rows.length ? (
        <div className="admin-panel__table-wrap">
        <table className="kr-table" aria-label="Product mapping">
          <thead><tr><th>Jira project</th><th>Product</th><th /></tr></thead>
          <tbody>
            {rows.map((row, index) => {
              const path = `releases.products[${index}]`;
              const code = errors[path];
              return (
                <Fragment key={row.id}>
                  <tr data-field={path}>
                    <td>
                      <input className={inputClass(Boolean(code))} list="kr-project-keys" aria-label={`Jira project of mapping ${index + 1}`}
                        placeholder="PROJ" value={row.projectKey}
                        onChange={(event) => update(index, { projectKey: event.target.value.toUpperCase() })} />
                    </td>
                    <td>
                      <input className={inputClass(Boolean(code))} aria-label={`Product of mapping ${index + 1}`}
                        placeholder="Product" value={row.product}
                        onChange={(event) => update(index, { product: event.target.value })} />
                    </td>
                    <td>
                      <button type="button" className="admin-panel__action-btn"
                        onClick={() => onChange(rows.filter((_, other) => other !== index))}>Remove</button>
                    </td>
                  </tr>
                  {code ? <tr><td colSpan={3}><FieldError path={path} code={code} /></td></tr> : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        </div>
      ) : (
        <div className="kr-help">No project is mapped yet: release sync stays in “needs configuration” until one is.</div>
      )}
      <datalist id="kr-project-keys">
        {projectKeys.map((key) => <option key={key} value={key} />)}
      </datalist>
      <div className="kr-row">
        <button type="button" className="admin-panel__action-btn" onClick={() => onChange([...rows, newProductRow()])}>
          Add mapping
        </button>
      </div>
    </>
  );
}

// Ordered sections: an issue lands in the first section whose issue types or labels it matches (case-insensitive);
// an issue no section matches is listed under its own Jira issue type.
export function ReleaseSectionsTable({ rows, errors, onChange }: {
  rows: SectionRow[];
  errors: FieldErrors;
  onChange: (rows: SectionRow[]) => void;
}) {
  const update = (index: number, patch: Partial<SectionRow>) =>
    onChange(rows.map((row, other) => (other === index ? { ...row, ...patch } : row)));
  return (
    <>
      {rows.length ? (
        <div className="admin-panel__table-wrap">
        <table className="kr-table" aria-label="Release note sections">
          <thead><tr><th>#</th><th>Section</th><th /></tr></thead>
          <tbody>
            {rows.map((row, index) => {
              const path = `releases.sections[${index}]`;
              const titleCode = errors[`${path}.title`];
              const sectionCode = errors[path];
              return (
                <tr key={row.id} data-field={path}>
                  <td className="admin-panel__muted">{index + 1}</td>
                  <td>
                    <div className="admin-panel__stack admin-panel__stack--compact">
                      <input className={inputClass(Boolean(titleCode))} aria-label={`Title of section ${index + 1}`}
                        placeholder="Title, e.g. New features" value={row.title}
                        onChange={(event) => update(index, { title: event.target.value })} />
                      {titleCode ? <FieldError path={`${path}.title`} code={titleCode} /> : null}
                      <div className="kr-help">Issue types</div>
                      <ReleaseTagList field={`releases.sections[${index}].issue_types`} label={`Issue types of section ${index + 1}`}
                        values={row.issueTypes} errors={errors} placeholder="e.g. Story"
                        onChange={(issueTypes) => update(index, { issueTypes })} />
                      <div className="kr-help">Labels</div>
                      <ReleaseTagList field={`releases.sections[${index}].labels`} label={`Labels of section ${index + 1}`}
                        values={row.labels} errors={errors} placeholder="e.g. breaking-change"
                        onChange={(labels) => update(index, { labels })} />
                      {sectionCode ? <FieldError path={path} code={sectionCode} /> : null}
                    </div>
                  </td>
                  <td>
                    <div className="admin-panel__stack admin-panel__stack--compact">
                      <button type="button" className="admin-panel__action-btn" disabled={index === 0}
                        onClick={() => onChange(moveRow(rows, index, -1))}>Move up</button>
                      <button type="button" className="admin-panel__action-btn" disabled={index === rows.length - 1}
                        onClick={() => onChange(moveRow(rows, index, 1))}>Move down</button>
                      <button type="button" className="admin-panel__action-btn"
                        onClick={() => onChange(rows.filter((_, other) => other !== index))}>Remove</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      ) : (
        <div className="kr-help">No sections: every issue is listed under its own Jira issue type.</div>
      )}
      {errorsFor(errors, "releases.sections").filter(([path]) => path === "releases.sections")
        .map(([path, code]) => <FieldError key={path} path={path} code={code} />)}
      <div className="kr-row">
        <button type="button" className="admin-panel__action-btn" onClick={() => onChange([...rows, newSectionRow()])}>
          Add section
        </button>
      </div>
    </>
  );
}
