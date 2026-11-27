"use client";

import type { CategoryCount } from "@/src/api/client";

/** "All" plus one chip per category (task 9.5). Renders nothing when there is nothing to choose. */
export function CategoryBar({
  categories,
  active,
  onSelect,
}: {
  categories: readonly CategoryCount[];
  active: string | null;
  onSelect: (category: string | null) => void;
}) {
  if (categories.length === 0) return null;
  const chips: { name: string | null; label: string; count?: number }[] = [
    { name: null, label: "All" },
    ...categories.map((c) => ({ name: c.name, label: c.name, count: c.stories })),
  ];
  return (
    <nav
      aria-label="Story categories"
      className="pointer-events-auto flex max-w-full gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]"
    >
      {chips.map((c) => {
        const selected = c.name === active;
        return (
          <button
            key={c.label}
            type="button"
            aria-pressed={selected}
            onClick={() => onSelect(c.name)}
            className={`shrink-0 rounded-full px-3 py-1 font-body text-xs uppercase tracking-[0.14em] transition-colors ${
              selected ? "bg-gold text-set" : "bg-black/55 text-white/80 hover:bg-black/75 hover:text-white"
            }`}
          >
            {c.label}
            {c.count !== undefined && (
              <span className={selected ? "ml-1.5 text-set/70" : "ml-1.5 text-white/45"}>{c.count}</span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
