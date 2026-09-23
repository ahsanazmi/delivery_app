export function Pagination({
  page,
  limit,
  total,
  onPageChange,
  itemLabel = "items",
}: {
  page: number;
  limit: number;
  total: number;
  onPageChange: (page: number) => void;
  itemLabel?: string;
}) {
  const totalPages = Math.max(1, Math.ceil(total / limit));
  if (totalPages <= 1 && total <= limit) {
    return null;
  }

  return (
    <div className="pagination-bar">
      <button className="btn-secondary" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        Previous
      </button>
      <span className="muted">
        Page {page} of {totalPages} ({total} {itemLabel})
      </span>
      <button className="btn-secondary" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
        Next
      </button>
    </div>
  );
}
