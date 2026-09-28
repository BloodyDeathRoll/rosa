import { useEffect, useRef, useState } from "preact/hooks";
import { fetchSpot } from "./api";
import { todayIn } from "./format";
import { swimDayView, type SwimDayView } from "./lib/swim";
import type { SpotPayload } from "./types";

/** Swim mode on screens that only hold the spot index (map pins and cards, search,
    the desktop ticker, nearby cards). The index carries the surf rating and range, not
    the hours a swim score needs, so the forecast is fetched on demand - only for spots
    on screen, six at a time - and the result is kept for the session. Nothing here
    runs in surf mode. Screens that already hold a payload `prime` it for free. */

const views = new Map<string, SwimDayView | null>(); // null = could not load
const pending = new Set<string>();
const queue: string[] = [];
const MAX_IN_FLIGHT = 6;
let inFlight = 0;
export const SWIM_DATA_EVENT = "rosa:swimdata";

let notifyTimer: ReturnType<typeof setTimeout> | undefined;
function notify(): void {
  if (notifyTimer !== undefined) return;
  notifyTimer = setTimeout(() => {
    notifyTimer = undefined;
    dispatchEvent(new Event(SWIM_DATA_EVENT));
  }, 120);
}

/** Today's swim reading from a payload the caller already holds. */
export function primeSwim(p: SpotPayload): void {
  if (views.get(p.spot.id)) return;
  views.set(p.spot.id, swimDayView(p, todayIn(p.spot.timezone)));
  notify();
}

function pump(): void {
  while (inFlight < MAX_IN_FLIGHT && queue.length) {
    const id = queue.shift()!;
    inFlight++;
    fetchSpot(id)
      .then(
        (p) => views.set(id, swimDayView(p, todayIn(p.spot.timezone))),
        () => views.set(id, null)
      )
      .finally(() => {
        inFlight--;
        pending.delete(id);
        notify();
        pump();
      });
  }
}

/** Queue these spots' forecasts (newest request first, so what just scrolled into
    view outranks what scrolled past). */
export function requestSwim(ids: string[]): void {
  const fresh = ids.filter((id) => !views.has(id) && !pending.has(id));
  for (const id of fresh) pending.add(id);
  queue.unshift(...fresh);
  pump();
}

export function swimViewOf(id: string): SwimDayView | null | undefined {
  return views.get(id);
}

/** Re-renders the caller whenever new swim readings land. */
export function useSwimTick(on: boolean): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!on) return;
    const bump = () => setTick((t) => t + 1);
    addEventListener(SWIM_DATA_EVENT, bump);
    return () => removeEventListener(SWIM_DATA_EVENT, bump);
  }, [on]);
  return tick;
}

/** One spot's swim reading, fetched once its element scrolls into view. Returns the
    reading (undefined while loading, null if the forecast would not load) and a ref
    for the element that should trigger the fetch. Inert in surf mode. */
export function useSwimView(
  id: string,
  on: boolean
): [SwimDayView | null | undefined, (el: Element | null) => void] {
  useSwimTick(on);
  const obs = useRef<IntersectionObserver | null>(null);
  useEffect(() => () => obs.current?.disconnect(), []);
  const ref = (el: Element | null) => {
    obs.current?.disconnect();
    obs.current = null;
    if (!on || !el || views.has(id)) return;
    if (typeof IntersectionObserver === "undefined") {
      requestSwim([id]);
      return;
    }
    obs.current = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) {
        obs.current?.disconnect();
        requestSwim([id]);
      }
    });
    obs.current.observe(el);
  };
  return [on ? views.get(id) : undefined, ref];
}
