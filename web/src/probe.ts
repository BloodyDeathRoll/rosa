/** Which app opens Rosa with `/?token=…&accountId=…&username=…&webview=ANDROID_WEBVIEW`?

    Since 2026-09-03 an unknown Android app opens rosa.surf inside itself and appends its
    own sign-in token (EdDSA JWT, `iss: token-service`, `aud: autologin`) - ~950 such
    loads from ~690 of its accounts by 2026-10-05, mostly Arabic-language phones, all
    "direct" in GA4. GA4 cannot say which app, so on exactly those loads this sends the
    browser's own description of itself to the user API (`POST /probe`), which adds the
    request headers and stores the row. TEMPORARY: delete this file, its call in
    main.tsx and the Worker route once the app is named.

    Sent: user agent, client hints (the `Android WebView` brand and the device model),
    referrer, display mode, which query keys were present, and the names of globals the
    host app injected into the page (a WebView bridge such as `flutter_inappwebview`
    usually names the toolkit, sometimes the app). Never sent: the token, the accountId
    or the username - they identify the other app's user, not anything we need. */

const API = (import.meta.env.VITE_USER_API as string | undefined) ?? "";

/** Bridges WebView toolkits are known to inject; checked by name on top of the diff below. */
const KNOWN_BRIDGES = [
  "Android",
  "AndroidBridge",
  "AndroidInterface",
  "JSBridge",
  "WebViewJavascriptBridge",
  "ReactNativeWebView",
  "flutter_inappwebview",
  "Capacitor",
  "cordova",
  "median",
  "gonative",
  "Unity",
  "AppInventor",
];

/** Globals on this window that a pristine same-origin frame does not have: our own
    (gtag, dataLayer, …) plus whatever the host app evaluated into the main frame. */
function injectedGlobals(): string[] {
  const frame = document.createElement("iframe");
  frame.style.display = "none";
  document.body.appendChild(frame);
  try {
    const clean = new Set(Object.getOwnPropertyNames(frame.contentWindow ?? {}));
    return Object.getOwnPropertyNames(window)
      .filter((k) => !clean.has(k))
      .slice(0, 80);
  } finally {
    frame.remove();
  }
}

/** True on exactly the loads described above: the app's own `webview=ANDROID_WEBVIEW`
    marker, or its token pair. Read once at boot, before the router touches the URL. */
const FROM_FOREIGN_APP = (() => {
  const q = new URLSearchParams(location.search);
  return q.get("webview") === "ANDROID_WEBVIEW" || (q.has("token") && q.has("accountId"));
})();

export const fromForeignApp = (): boolean => FROM_FOREIGN_APP;

/** The visitor's own answer to "which app sent you here?" (ForeignAppAsk.tsx). Same
    route, same table; `kind` tells the rows apart. */
export function sendForeignAppAnswer(answer: string, lang: string): void {
  if (!API) return;
  fetch(`${API}/probe`, {
    method: "POST",
    body: JSON.stringify({ kind: "answer", answer: answer.slice(0, 200), lang, ua: navigator.userAgent }),
    keepalive: true,
  }).catch(() => undefined);
}

export function probeForeignApp(): void {
  const q = new URLSearchParams(location.search);
  if (!API || !FROM_FOREIGN_APP) return;
  void (async () => {
    const nav = navigator as Navigator & {
      userAgentData?: { getHighEntropyValues(h: string[]): Promise<Record<string, unknown>> };
    };
    let hints: Record<string, unknown> | null = null;
    try {
      hints = (await nav.userAgentData?.getHighEntropyValues(["model", "platformVersion", "fullVersionList"])) ?? null;
    } catch {
      hints = null;
    }
    let globals: string[] = [];
    try {
      globals = injectedGlobals();
    } catch {
      globals = [];
    }
    const body = {
      ua: navigator.userAgent,
      hints,
      referrer: document.referrer,
      standalone: matchMedia("(display-mode: standalone)").matches,
      keys: [...q.keys()],
      webview: q.get("webview"),
      globals,
      bridges: KNOWN_BRIDGES.filter((k) => k in window),
      lang: navigator.language,
    };
    // text/plain keeps it a simple request: no CORS preflight, which some WebViews mishandle
    await fetch(`${API}/probe`, { method: "POST", body: JSON.stringify(body), keepalive: true });
  })().catch(() => undefined);
}
