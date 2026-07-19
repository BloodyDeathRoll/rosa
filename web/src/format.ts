/** Small formatting helpers. All times in payloads are already spot-local ISO strings. */

export function hourOf(iso: string): string {
  return iso.slice(11, 16);
}

export function dateOf(iso: string): string {
  return iso.slice(0, 10);
}

export function dayLabel(date: string, today: string): string {
  if (date === today) return "Today";
  const names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return names[new Date(`${date}T12:00:00`).getDay()] ?? date;
}

export function heightRange(h: [number, number]): string {
  const [lo, hi] = h;
  if (hi === 0) return "flat";
  return lo === hi ? `${lo} m` : `${lo}–${hi} m`;
}

/** Compass arrow rotation: met. directions are "coming FROM", arrow shows where it goes. */
export function arrowRotation(fromDeg: number): number {
  return (fromDeg + 180) % 360;
}
