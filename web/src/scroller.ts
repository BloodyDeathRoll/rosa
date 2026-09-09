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

/** Freeze the page behind a full-screen overlay; the returned function thaws it.
 *
 * Counted, because overlays overlap: the sign-in screen and the report nudge are
 * both up on a signed-out first launch. Each saving and restoring
 * `body.style.overflow` itself meant the second one to open saved the first
 * one's "hidden" and wrote it back on close, leaving the whole app unscrollable
 * (2026-09-09). Only the last lock released restores the page. */
let locks = 0;
let unlocked = "";

export function lockScroll(): () => void {
  if (locks === 0) {
    unlocked = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  locks += 1;
  let released = false;
  return () => {
    if (released) return; // a double-release must not free someone else's lock
    released = true;
    locks -= 1;
    if (locks === 0) document.body.style.overflow = unlocked;
  };
}
