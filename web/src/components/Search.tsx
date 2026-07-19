import { useMemo, useRef, useState } from "preact/hooks";
import type { SpotIndex } from "../types";

interface Item {
  id: string;
  name: string;
}

export function Search({ index }: { index: SpotIndex }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const items = useMemo<Item[]>(
    () => Object.entries(index.spots).map(([id, e]) => ({ id, name: e.name })),
    [index]
  );

  const q = query.trim().toLowerCase();
  const matches = q
    ? items.filter((s) => s.name.toLowerCase().includes(q) || s.id.includes(q)).slice(0, 6)
    : [];

  const go = (id: string) => {
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
    location.hash = `#/spot/${id}`;
  };

  return (
    <div class="search" role="combobox" aria-expanded={open && matches.length > 0}>
      <input
        ref={inputRef}
        type="search"
        placeholder="Search spots"
        aria-label="Search spots"
        value={query}
        onInput={(e) => {
          setQuery((e.target as HTMLInputElement).value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && matches[0]) go(matches[0].id);
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && matches.length > 0 && (
        <ul class="search-results" role="listbox">
          {matches.map((s) => (
            <li key={s.id} role="option">
              <button onMouseDown={() => go(s.id)}>{s.name}</button>
            </li>
          ))}
        </ul>
      )}
      {open && q && matches.length === 0 && (
        <ul class="search-results">
          <li class="search-empty">No spots match "{query}" yet</li>
        </ul>
      )}
    </div>
  );
}
