import type { IndexEntry } from "../types";

export const ALL_GROUP = "All";

/** Region groups present among the given entries, "All" first (Surfline-style
    favorites group bar). Returns just ["All"] when there are no entries. */
export function groupsOf(rows: [string, IndexEntry][]): string[] {
  const seen: string[] = [];
  for (const [, e] of rows) {
    const g = e.region?.trim() || "Other";
    if (!seen.includes(g)) seen.push(g);
  }
  return [ALL_GROUP, ...seen];
}

/** Horizontal, scrollable group pills - the selected one is filled. */
export function GroupChips({
  groups,
  selected,
  onSelect,
}: {
  groups: string[];
  selected: string;
  onSelect: (g: string) => void;
}) {
  return (
    <div class="group-chips" role="tablist" aria-label="Region groups">
      {groups.map((g) => (
        <button
          key={g}
          role="tab"
          aria-selected={g === selected}
          class={`group-chip${g === selected ? " on" : ""}`}
          onClick={() => onSelect(g)}
        >
          {g}
        </button>
      ))}
    </div>
  );
}
