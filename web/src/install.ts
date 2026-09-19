/** Add-to-home-screen offer, made when Rosa is running in a browser tab rather
    than as an installed PWA. The sheet keeps offering itself until the user
    actually answers it - a sheet nobody looked at was never an answer - and then
    stays quiet for the rest of that tab session (the flag lives in sessionStorage,
    which survives a reload but not a fresh launch). Profile carries a standing
    Install row for anyone who said no and changed their mind. */

const SEEN_KEY = "rosa.install.seen";

/** The Google Play app (android/twa-manifest.json): a Trusted Web Activity, i.e.
    this same site inside Chrome. It and a Chrome-installed PWA share one origin
    (storage, sign-in, push), so having both is only two icons - but nothing on
    the web can remove an icon, so the PWA stops being offered once the Play app
    is there, and a PWA that finds it says once that it is the spare one. */
const PLAY_APP_ID = "surf.rosa.app";
const TWA_KEY = "rosa.twa";
const DUPLICATE_SEEN_KEY = "rosa.duplicate.seen";

interface RelatedApp {
  platform: string;
  id?: string;
}
type RelatedAppsNavigator = Navigator & {
  getInstalledRelatedApps?: () => Promise<RelatedApp[]>;
};

let playAppInstalled = false;

/** Ask Chrome whether the Play app is on this phone (it answers from the
    manifest's `related_applications` + assetlinks.json; every other browser has
    no such API and stays false). Called once at startup; re-broadcasts
    `rosa:installable` so the Profile row re-reads its offer. */
export async function detectPlayApp(): Promise<boolean> {
  try {
    const apps = (await (navigator as RelatedAppsNavigator).getInstalledRelatedApps?.()) ?? [];
    playAppInstalled = apps.some((a) => a.platform === "play" && a.id === PLAY_APP_ID);
  } catch {
    playAppInstalled = false;
  }
  if (playAppInstalled) dispatchEvent(new Event("rosa:installable"));
  return playAppInstalled;
}

/** Running INSIDE the Play app? A TWA's first document carries the package as its
    referrer; the flag rides sessionStorage so a reload inside it still knows. */
export function inPlayApp(): boolean {
  try {
    if (document.referrer.startsWith(`android-app://${PLAY_APP_ID}`)) {
      sessionStorage.setItem(TWA_KEY, "1");
      return true;
    }
    return sessionStorage.getItem(TWA_KEY) === "1";
  } catch {
    return document.referrer.startsWith(`android-app://${PLAY_APP_ID}`);
  }
}

/** This is the installed PWA and the Play app is on the phone too - so this icon
    is the spare. Said once per device. */
export function duplicateNoteDue(): boolean {
  if (!playAppInstalled || !installed() || inPlayApp()) return false;
  try {
    return localStorage.getItem(DUPLICATE_SEEN_KEY) !== "1";
  } catch {
    return true; // storage blocked - once per page load is the best we can do
  }
}

export function markDuplicateSeen(): void {
  try {
    localStorage.setItem(DUPLICATE_SEEN_KEY, "1");
  } catch {
    // ignore
  }
}

/** Chrome's deferred install event - not in lib.dom, and only ever usable once. */
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

type BipWindow = Window & { __ROSA_BIP?: BeforeInstallPromptEvent | null };

/** "prompt" = Chromium will show the real dialog. "chrome" = Samsung Internet, sent
    to Chrome to install (see samsungAndroid). The rest are browsers that can
    install but expose no API for it, so all we can do is say where the control
    is. Browsers with no install path at all get nothing. */
export type InstallOffer = "prompt" | "chrome" | "ios" | "firefox";

function deferred(): BeforeInstallPromptEvent | null {
  return (window as BipWindow).__ROSA_BIP ?? null;
}

/** Already running as an installed app (Android/desktop standalone, or iOS's
    own flag), so there is nothing to offer. */
function installed(): boolean {
  return (
    matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

/** Only Safari can add to the iOS home screen - Chrome/Firefox/Edge on iOS are
    Safari skins without the Share > Add to Home Screen entry, so telling their
    users to look for it would send them hunting for a menu that isn't there. */
function iosSafari(): boolean {
  const ua = navigator.userAgent;
  const isIos =
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); // iPadOS
  return isIos && /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
}

/** Firefox never fires beforeinstallprompt - it's a Chromium-only API. On Android
    it can still install from its own menu, so point there; on desktop Firefox has
    no install path at all and gets no offer rather than a dead-end instruction. */
function firefoxAndroid(): boolean {
  const ua = navigator.userAgent;
  return /Firefox\//.test(ua) && /Android/.test(ua);
}

/** Samsung Internet fires beforeinstallprompt, but the app it installs is wrapped by
    Samsung's own server with an old Android target, and Play Protect on Android 14+
    blocks it as an unsafe app (SamsungInternet/support#123, open since 2026-04).
    Chrome's wrapper is current, so these users install from Chrome instead. */
function samsungAndroid(): boolean {
  const ua = navigator.userAgent;
  return /SamsungBrowser\//.test(ua) && /Android/.test(ua);
}

/** What (if anything) this browser can be told about installing, ignoring the
    once-per-open flag - for the Profile row, which the user went looking for
    rather than being interrupted by. */
export function manualInstallOffer(): InstallOffer | null {
  if (installed() || playAppInstalled) return null;
  if (samsungAndroid()) return "chrome";
  if (deferred()) return "prompt";
  if (iosSafari()) return "ios";
  return firefoxAndroid() ? "firefox" : null;
}

/** What (if anything) to offer right now, unprompted. */
export function installOffer(): InstallOffer | null {
  try {
    if (sessionStorage.getItem(SEEN_KEY) === "1") return null;
  } catch {
    // private mode with storage blocked - offering once per page load is fine
  }
  return manualInstallOffer();
}

/** Remember that this open has been asked, so a refresh stays quiet. */
export function markInstallSeen(): void {
  try {
    sessionStorage.setItem(SEEN_KEY, "1");
  } catch {
    // ignore - worst case the sheet reappears on the next reload
  }
}

/** Reopen Rosa in Chrome through an Android intent link, where the install is
    clean. The current path rides along; the intent's own fragment is
    `#Intent;...`. No
    Chrome on the phone: the fallback is Chrome's Play Store page. */
export function openInChrome(): void {
  const fallback = encodeURIComponent(
    "https://play.google.com/store/apps/details?id=com.android.chrome",
  );
  location.href =
    `intent://${location.host}${location.pathname}${location.search}` +
    `#Intent;scheme=https;package=com.android.chrome;S.browser_fallback_url=${fallback};end`;
}

/** Hand over to Chrome's own install dialog. Resolves once the user has answered
    it; the deferred event is spent either way. */
export async function runInstall(): Promise<boolean> {
  const e = deferred();
  if (!e) return false;
  (window as BipWindow).__ROSA_BIP = null;
  await e.prompt();
  const { outcome } = await e.userChoice;
  return outcome === "accepted";
}
