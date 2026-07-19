const KEY = "rosa.recents";
const MAX = 8;

export function getRecents(): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function pushRecent(id: string): void {
  const next = [id, ...getRecents().filter((x) => x !== id)].slice(0, MAX);
  localStorage.setItem(KEY, JSON.stringify(next));
}
