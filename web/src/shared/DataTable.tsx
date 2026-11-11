/** DataTable: typed table with sortable headers and row click. */

import { useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  sortValue?: (row: T) => string | number;
  className?: string;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  empty?: ReactNode;
  /** Optional per-row class (e.g. to briefly highlight freshly arrived rows). */
  rowClassName?: (row: T) => string | undefined;
}

export function DataTable<T>({ columns, rows, rowKey, onRowClick, empty, rowClassName }: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sorted = (() => {
    if (!sortKey) return rows;
    const col = columns.find((c) => c.key === sortKey);
    if (!col?.sortValue) return rows;
    const out = [...rows].sort((a, b) => {
      const av = col.sortValue!(a);
      const bv = col.sortValue!(b);
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return out;
  })();

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  if (rows.length === 0 && empty) {
    return <div className="py-6 text-center text-sm text-muted">{empty}</div>;
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface shadow-card">
      <table className="w-full text-sm">
        <thead className="border-b border-border bg-surface-2 text-left text-xs uppercase tracking-wide text-muted">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-3 font-medium ${col.sortValue ? "cursor-pointer select-none hover:text-ink" : ""} ${col.className ?? ""}`}
                onClick={() => col.sortValue && toggleSort(col.key)}
              >
                {col.header}
                {sortKey === col.key && (
                  <span className="ml-1 text-accent" aria-hidden="true">
                    {sortDir === "asc" ? "▲" : "▼"}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr
              key={rowKey(row)}
              className={`border-b border-border/60 last:border-0 ${onRowClick ? "cursor-pointer hover:bg-surface-2" : ""} ${rowClassName?.(row) ?? ""}`}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((col) => (
                <td key={col.key} className={`px-4 py-3 text-ink ${col.className ?? ""}`}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
