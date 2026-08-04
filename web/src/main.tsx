import { render } from "preact";
import { initAnalytics } from "./analytics";
import { App } from "./app";
import { appReady } from "./splash";
import "@fontsource-variable/inter";
import "./styles.css";

const root = document.getElementById("app");
if (root) render(<App />, root);

initAnalytics();

/** Pick up a new deploy on the first launch instead of the second.
    The worker is built with skipWaiting + clientsClaim, so an update activates and
    claims this page immediately - but the JS already running is still the old
    build, which is why a fresh deploy used to need two launches to show up. */
function reloadOnUpdate(): void {
  if (!("serviceWorker" in navigator)) return;
  // No controller means this is the first ever load: the worker that claims the
  // page is the initial install, not an update, and reloading would be a pointless
  // flash on a first visit.
  if (!navigator.serviceWorker.controller) return;
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloading) return; // the event can fire more than once
    reloading = true;
    location.reload(); // keeps the hash, so you land back on the same screen
  });
}
reloadOnUpdate();

/** Dismiss the branded splash once the app is actually ready to show real content:
    hold until the initial page's data has loaded (`appReady`), the webfont is ready
    (so the wordmark never swaps), and a ≥1 s minimum has elapsed. A hard cap keeps a
    stalled network from trapping the user on the splash forever. */
function dismissSplash(): void {
  const el = document.getElementById("splash");
  if (!el) return;
  const start = (window as unknown as { __ROSA_SPLASH_T?: number }).__ROSA_SPLASH_T ?? Date.now();
  const minShow = new Promise<void>((r) => setTimeout(r, Math.max(0, 1000 - (Date.now() - start))));
  const fontsReady = (document as Document & { fonts?: FontFaceSet }).fonts?.ready ?? Promise.resolve();
  const cap = new Promise<void>((r) => setTimeout(r, 10000)); // safety net
  const dataReady = Promise.race([appReady, cap]);
  void Promise.all([minShow, fontsReady, dataReady]).then(() => {
    el.classList.add("hide");
    el.addEventListener("transitionend", () => el.remove(), { once: true });
    // fallback removal in case the transition never fires (e.g. reduced motion)
    setTimeout(() => el.remove(), 700);
  });
}
dismissSplash();
