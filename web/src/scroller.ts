/** Whatever is actually scrolling the app.
 *
 * The document scrolls at every width now (the phone frame that once gave .page
 * its own scrollbar on wide screens is gone, 2026-09-08), but the full-bleed
 * screens still own an inner scroller of their own, so these helpers keep
 * reading both - callers never have to know which one is live. */

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
