import type { IndexEntry } from "../types";

export const ALL_GROUP = "All";
const OTHER_GROUP = "Other";

export function groupNameOf(region: string | null | undefined): string {
  return region?.trim() || OTHER_GROUP;
}

/** Split a list into region sections, in the order the regions first appear.
    Same grouping and same order as the chip bar, so a section heading always
    reads as the chip that would filter to it. Order within a section is left
    alone, so an already north-to-south list stays that way. */
export function sectionsOf<T>(
  rows: T[],
  regionOf: (row: T) => string | null | undefined
): { group: string; rows: T[] }[] {
  const out: { group: string; rows: T[] }[] = [];
  for (const row of rows) {
    const group = groupNameOf(regionOf(row));
    const section = out.find((s) => s.group === group);
    if (section) section.rows.push(row);
    else out.push({ group, rows: [row] });
  }
  return out;
}

/** Region groups present among the given entries, "All" first (Surfline-style
    favorites group bar). Returns just ["All"] when there are no entries. */
export function groupsOf(rows: [string, IndexEntry][]): string[] {
  return [ALL_GROUP, ...sectionsOf(rows, ([, e]) => e.region).map((s) => s.group)];
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
