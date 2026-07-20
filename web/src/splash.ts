/** Splash coordination. A page calls `signalReady()` once its initial data is on
    screen; `appReady` resolves on the first such call. main.tsx holds the branded
    splash until then (bounded by a hard cap), so the app is already populated when
    the splash lifts — no empty "Loading…" flash in between. */
let resolve: () => void = () => {};
export const appReady: Promise<void> = new Promise((r) => {
  resolve = r;
});

let fired = false;
export function signalReady(): void {
  if (fired) return;
  fired = true;
  resolve();
}
