export function ThreadDraftRow({ onSelect }: { onSelect: () => void }) {
  return (
    <div className="thread-node" role="treeitem" aria-selected="true">
      <div className="thread-node__row">
        <button
          type="button"
          className="thread-card thread-card--active thread-card--draft"
          onClick={onSelect}
        >
          <div className="thread-card__header">
            <div className="thread-card__title-line">
              <span className="thread-card__status thread-card__status--none" aria-hidden="true" />
              <span className="thread-card__title-text">New chat</span>
              <span className="thread-card__draft-tag">Draft</span>
            </div>
          </div>
        </button>
      </div>
    </div>
  );
}
