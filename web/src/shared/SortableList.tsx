/** SortableList: keyboard-accessible drag-to-reorder list.
 *
 * Each item has a grab handle. Keyboard users focus the handle and use
 * ArrowUp/ArrowDown to move the item. The order is lifted to the parent via
 * `onChange(newOrder)`. Rows are rendered by the caller via `renderRow`,
 * which receives the item, its position, and an escalation label.
 */

import { useState, type ReactNode } from "react";
import { GripVertical } from "lucide-react";

export interface SortableItem {
  id: string;
  label: string;
}

export interface SortableListProps {
  items: SortableItem[];
  onChange: (items: SortableItem[]) => void;
  /** Render the row body (avatar, name, badges, actions). The handle + position are added by the list. */
  renderRow?: (item: SortableItem, index: number) => ReactNode;
  /** Optional label per position, e.g. "Notified first" / "then …". */
  positionLabel?: (index: number, total: number) => string;
}

export function SortableList({ items, onChange, renderRow, positionLabel }: SortableListProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  function move(from: number, to: number) {
    if (to < 0 || to >= items.length || from === to) return;
    const next = [...items];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    onChange(next);
    setActiveIndex(to);
  }

  return (
    <ul className="divide-y divide-border rounded-lg border border-border bg-surface shadow-card" role="list">
      {items.map((item, index) => {
        const isActive = activeIndex === index;
        const pos = positionLabel?.(index, items.length) ?? `#${index + 1}`;
        return (
          <li
            key={item.id}
            className={`flex items-center gap-3 px-3 py-2.5 ${isActive ? "bg-accent-soft" : ""}`}
          >
            <button
              type="button"
              aria-label={`Reorder ${item.label}. Use up and down arrows to move.`}
              className="cursor-grab text-muted hover:text-ink focus:outline-none focus:ring-2 focus:ring-accent"
              onFocus={() => setActiveIndex(index)}
              onBlur={() => setActiveIndex(null)}
              onKeyDown={(e) => {
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  move(index, index - 1);
                } else if (e.key === "ArrowDown") {
                  e.preventDefault();
                  move(index, index + 1);
                }
              }}
            >
              <GripVertical className="h-4 w-4" aria-hidden="true" />
            </button>
            <span className="w-20 shrink-0 text-xs font-medium text-muted">{pos}</span>
            <span className="flex-1">{renderRow ? renderRow(item, index) : <span className="text-sm text-ink">{item.label}</span>}</span>
          </li>
        );
      })}
    </ul>
  );
}
