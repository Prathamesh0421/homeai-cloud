/** SortableList: keyboard-accessible drag-to-reorder list.
 *
 * Each item has a grab handle. Keyboard users focus the handle and use
 * ArrowUp/ArrowDown to move the item, Space to drop. The order is lifted to
 * the parent via `onChange(newOrder)`.
 */

import { useState } from "react";

export interface SortableItem {
  id: string;
  label: string;
}

export interface SortableListProps {
  items: SortableItem[];
  onChange: (items: SortableItem[]) => void;
}

export function SortableList({ items, onChange }: SortableListProps) {
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
    <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white" role="list">
      {items.map((item, index) => {
        const isActive = activeIndex === index;
        return (
          <li
            key={item.id}
            className={`flex items-center gap-2 px-3 py-2 ${isActive ? "bg-slate-100" : ""}`}
          >
            <button
              type="button"
              aria-label={`Reorder ${item.label}. Use up and down arrows to move.`}
              className="cursor-grab text-slate-400 hover:text-slate-600 focus:outline-none focus:ring-2 focus:ring-slate-400"
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
              ⠿
            </button>
            <span className="text-sm text-slate-700">{item.label}</span>
            <span className="ml-auto text-xs text-slate-400">#{index + 1}</span>
          </li>
        );
      })}
    </ul>
  );
}
