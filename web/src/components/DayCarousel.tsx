import type { ComponentChildren } from "preact";
import { useEffect, useRef } from "preact/hooks";

/** Full-width day panels in a native scroll-snap track: the whole block follows the
    finger as you drag and snaps to the nearest day on release. Coupled to the date bar
    via `selected`/`onSelect`. Content is virtualized to the selected ±1 window so the
    heavy cards (maps, sparks) only mount near the viewport; `scroll-snap-stop: always`
    keeps a fling from skipping past an unrendered panel. */
export function DayCarousel({
  count,
  selected,
  onSelect,
  renderPanel,
}: {
  count: number;
  selected: number;
  onSelect: (i: number) => void;
  renderPanel: (i: number) => ComponentChildren;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const programmatic = useRef(false);
  const clearTimer = useRef<number | undefined>(undefined);

  // scroll to the selected day when it changes from outside a drag (date-bar tap)
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const w = el.clientWidth || 1;
    const target = selected * w;
    if (Math.abs(el.scrollLeft - target) < 2) return; // already there (e.g. a drag just snapped)
    const far = Math.abs(el.scrollLeft / w - selected) > 1.5;
    programmatic.current = true;
    el.scrollTo({ left: target, behavior: far ? "auto" : "smooth" });
    clearTimeout(clearTimer.current);
    clearTimer.current = window.setTimeout(() => (programmatic.current = false), 500);
  }, [selected]);

  // when a user drag settles, adopt the snapped panel as the selected day
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScrollEnd = () => {
      if (programmatic.current) {
        programmatic.current = false;
        return;
      }
      const i = Math.round(el.scrollLeft / (el.clientWidth || 1));
      if (i !== selected && i >= 0 && i < count) onSelect(i);
    };
    el.addEventListener("scrollend", onScrollEnd);
    return () => el.removeEventListener("scrollend", onScrollEnd);
  }, [selected, count, onSelect]);

  return (
    <div class="day-carousel" ref={ref}>
      {Array.from({ length: count }, (_, i) => (
        <div class="day-panel" key={i}>
          {Math.abs(i - selected) <= 1 ? renderPanel(i) : null}
        </div>
      ))}
    </div>
  );
}
