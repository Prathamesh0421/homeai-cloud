/** Pagination: page controls driven by total + page size. */

export interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onChange }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <div className="flex items-center justify-between px-1 py-2 text-sm text-muted">
      <span className="text-xs text-muted">
        {from}–{to} of {total}
      </span>
      <div className="flex gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="rounded-md border border-border-strong px-2.5 py-1.5 disabled:opacity-40 hover:bg-surface-2"
        >
          Prev
        </button>
        <span className="px-2.5 py-1.5 text-xs text-muted">
          {page} / {pages}
        </span>
        <button
          type="button"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
          className="rounded-md border border-border-strong px-2.5 py-1.5 disabled:opacity-40 hover:bg-surface-2"
        >
          Next
        </button>
      </div>
    </div>
  );
}
