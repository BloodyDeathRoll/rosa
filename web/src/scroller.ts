/** Whatever is actually scrolling the app.
 *
 * On a phone the document scrolls. On a wide screen the app renders inside a
 * device-shaped frame and .page owns the scrollbar instead - the frame itself
 * must stay put, because it is the containing block for the fixed bottom glow
 * (see the desktop block at the end of styles.css). These helpers work either
 * way, so callers never have to know which one is live - including across a
 * resize that flips the breakpoint. */

const inner = (): HTMLElement | null => document.querySelector<HTMLElement>(".app .page");

export function scrollTop(): number {
  const doc = window.scrollY || document.documentElement.scrollTop;
  return Math.max(inner()?.scrollTop ?? 0, doc);
}

export function scrollToTop(): void {
  const el = inner();
  if (el) el.scrollTop = 0;
  scrollTo(0, 0);
}

/** Subscribe to scrolls of either scroller; returns the unsubscribe. */
export function onScroll(fn: () => void): () => void {
  const el = inner();
  addEventListener("scroll", fn, { passive: true });
  el?.addEventListener("scroll", fn, { passive: true });
  return () => {
    removeEventListener("scroll", fn);
    el?.removeEventListener("scroll", fn);
  };
}
