import { useEffect, useRef } from "preact/hooks";
import { dayLabel, dayNum } from "../format";

/** Draggable date strip: day-of-week over date number, up to 16 days. Tap a date
    or drag and let it settle → onSelect. The selected date scrolls to center. Pairs
    with a content-swipe (see useDaySwipe) so both stay in sync. */
export function DateBar({
  dates,
  selected,
  live,
  today,
  onSelect,
}: {
  dates: string[];
  selected: number;
  /** index to highlight while a drag is in flight; falls back to `selected` */
  live?: number;
  today: string;
  onSelect: (i: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const selRef = useRef<HTMLButtonElement>(null);
  // true while a programmatic (centering) scroll is in flight — its scrollend must not
  // be mistaken for a user drag and re-snap mid-animation.
  const programmatic = useRef(false);

  // center the selected date when it changes (tap, swipe, or external)
  useEffect(() => {
    programmatic.current = true;
    selRef.current?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  }, [selected]);

  // when scrolling stops: if it was our centering scroll, just clear the flag; if it was
  // the user dragging the strip, snap to the nearest date and select it.
  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    const onScrollEnd = () => {
      if (programmatic.current) {
        programmatic.current = false;
        return;
      }
      const center = track.scrollLeft + track.clientWidth / 2;
      let best = selected;
      let bestD = Infinity;
      Array.from(track.children).forEach((c, i) => {
        const el = c as HTMLElement;
        const d = Math.abs(el.offsetLeft + el.offsetWidth / 2 - center);
        if (d < bestD) {
          bestD = d;
          best = i;
        }
      });
      if (best !== selected) onSelect(best);
    };
    track.addEventListener("scrollend", onScrollEnd);
    return () => track.removeEventListener("scrollend", onScrollEnd);
  }, [selected, onSelect]);

  const hi = live ?? selected;
  return (
    <div class="date-bar">
      <div class="track" ref={trackRef}>
        {dates.map((date, i) => (
          <button
            key={date}
            ref={i === selected ? selRef : undefined}
            class={`date-chip${i === hi ? " on" : ""}`}
            aria-current={i === hi ? "date" : undefined}
            onClick={() => onSelect(i)}
          >
            <span class="dow">{dayLabel(date, today)}</span>
            <span class="dnum tabular">{dayNum(date)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
