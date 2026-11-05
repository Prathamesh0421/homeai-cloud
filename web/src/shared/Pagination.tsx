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
    <div className="flex items-center justify-between px-1 py-2 text-sm text-slate-600">
      <span className="text-xs text-slate-500">
        {from}–{to} of {total}
      </span>
      <div className="flex gap-1">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40 hover:bg-slate-50"
        >
          Prev
        </button>
        <span className="px-2 py-1 text-xs text-slate-500">
          {page} / {pages}
        </span>
        <button
          type="button"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
          className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40 hover:bg-slate-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}
