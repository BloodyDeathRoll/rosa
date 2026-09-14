import { render } from "preact";
import { syncFavorites } from "./account";
import { initAnalytics } from "./analytics";
import { initGa, gaEvent, gaSetPrefs, unitsTag } from "./ga";
import { App } from "./app";
import { MovedScreen, onLegacyOrigin } from "./components/MovedScreen";
import { getFavorites, setFavorites } from "./favorites";
import { signedIn } from "./session";
import { getUnits } from "./units";
import { initialTheme } from "./theme";
import { mountParticles } from "./components/particles";
import { appReady } from "./splash";
import { adoptLegacyHash } from "./router";
import "@fontsource-variable/inter";
import "./styles.css";

/** `/spots?import=a,b,c` - favorites handed over from the old origin's app
    (MovedScreen). Storage is per origin, so this is the only way they cross.
    Merged into this device's list before anything renders; the sign-in screen
    then asks for the account they get saved to (signInWithCode merges local
    into the account). The parameter is stripped so a reload does not re-import. */
function importFromQuery(): void {
  const m = /[?&]import=([^&]+)/.exec(location.search);
  if (!m?.[1]) return;
  const ids = decodeURIComponent(m[1])
    .split(",")
    .filter((id) => /^[\w-]{1,64}$/.test(id));
  const current = getFavorites();
  const merged = [...current, ...ids.filter((id) => !current.includes(id))];
  if (merged.length !== current.length) setFavorites(merged, { dirty: signedIn() });
  history.replaceState(null, "", location.pathname + location.search.replace(/[?&]import=[^&]+/, ""));
}
// old `#/...` links (push notifications, shares, the old origin's hand-over)
// become their path form before the router reads them
adoptLegacyHash();
if (!onLegacyOrigin()) importFromQuery();

const root = document.getElementById("app");
if (root) {
  // the prerendered shell carries crawler text inside #app (index.html and
  // scripts/prerender.mjs); it is not hydrated, the app renders over a clean root
  root.replaceChildren();
  render(onLegacyOrigin() ? <MovedScreen /> : <App />, root);
}

initAnalytics();
// GA4 alongside it, and inert without VITE_GA_ID. Consent defaults are pushed inside
// initGa BEFORE gtag.js loads, which is the order Consent Mode requires.
initGa();
gaSetPrefs({
  units: unitsTag(getUnits()),
  theme: String(initialTheme()),
  signed_in: signedIn(),
  favorites: getFavorites().length,
  installed: matchMedia("(display-mode: standalone)").matches,
});
// The install itself, counted on its FIRST LAUNCH as an installed app - not on Chrome's
// `appinstalled`, which is what it was until 2026-09-14 and counted nothing: GA4 holds
// every event for 5 s before it sends (measured on the live site, beacon transport
// included), and on Android that event fires as the new app opens and the browser tab
// is backgrounded, so the hit died unsent. iOS fires no event at all. A launch outlives
// the batch window. Once per device: the installed app and the browser share the
// origin's localStorage, so the key set here is seen by both.
function countInstall(): void {
  if (!matchMedia("(display-mode: standalone)").matches) return;
  const KEY = "rosa.install.counted";
  try {
    if (localStorage.getItem(KEY)) return;
    localStorage.setItem(KEY, new Date().toISOString());
  } catch {
    return; // no storage - better an uncounted install than one counted every launch
  }
  gaEvent("app_install");
}
countInstall();

/** Favorites live on the server since 2026-09-07: push a list the last session
    could not save, or pull what another device changed. Silent, after paint. */
void appReady.then(() => syncFavorites());
addEventListener("online", () => void syncFavorites());

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
    location.reload(); // keeps the path, so you land back on the same screen
  });
}
reloadOnUpdate();

/** The splash carries the app's bottom treatment: the gradient mesh is inline CSS
    in index.html (it has to paint before this bundle exists), and the particle
    field starts here, the moment the bundle parses. The splash is up for at least
    a second after that, and the handle is stopped when it lifts. */
function splashParticles(el: HTMLElement): { stop(): void } | null {
  const canvas = el.querySelector<HTMLCanvasElement>(".splash-particles");
  if (!canvas || matchMedia("(prefers-reduced-motion: reduce)").matches) return null;
  try {
    return mountParticles(canvas, {
      palette: ["125, 185, 240", "94, 205, 205"],
      density: 1.4,
      speed: 1,
      alpha: 0.3,
    });
  } catch {
    return null; // no 2D context - the mesh alone carries the look
  }
}

/** Dismiss the branded splash once the app is actually ready to show real content:
    hold until the initial page's data has loaded (`appReady`), the webfont is ready
    (so the wordmark never swaps), and a ≥1 s minimum has elapsed. A hard cap keeps a
    stalled network from trapping the user on the splash forever. */
function dismissSplash(): void {
  const el = document.getElementById("splash");
  if (!el) return;
  const specks = splashParticles(el);
  const start = (window as unknown as { __ROSA_SPLASH_T?: number }).__ROSA_SPLASH_T ?? Date.now();
  const minShow = new Promise<void>((r) => setTimeout(r, Math.max(0, 1000 - (Date.now() - start))));
  const fontsReady = (document as Document & { fonts?: FontFaceSet }).fonts?.ready ?? Promise.resolve();
  const cap = new Promise<void>((r) => setTimeout(r, 10000)); // safety net
  const dataReady = Promise.race([appReady, cap]);
  void Promise.all([minShow, fontsReady, dataReady]).then(() => {
    specks?.stop();
    el.classList.add("hide");
    el.addEventListener("transitionend", () => el.remove(), { once: true });
    // fallback removal in case the transition never fires (e.g. reduced motion)
    setTimeout(() => el.remove(), 700);
  });
}
dismissSplash();
