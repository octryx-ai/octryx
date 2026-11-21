// The page switch under an Observability list: "Page n of m" with Previous and Next.
export function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (page: number) => void }) {
  return (
    <div className="ob-row">
      <span className="ob-muted">Page {page} of {pages}</span>
      <button type="button" className="admin-panel__action-btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
      <button type="button" className="admin-panel__action-btn" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
    </div>
  );
}
