import { render } from "preact";
import { App } from "./app";
import { appReady } from "./splash";
import "@fontsource-variable/inter";
import "./styles.css";

const root = document.getElementById("app");
if (root) render(<App />, root);

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
