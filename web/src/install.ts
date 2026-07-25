/** Add-to-home-screen offer. Shown once per app open when Rosa is running in a
    browser tab rather than as an installed PWA - a reload inside the same tab is
    the same open, so the sheet doesn't come back on every refresh (the seen flag
    lives in sessionStorage, which survives a reload but not a fresh launch). */

const SEEN_KEY = "rosa.install.seen";

/** Chrome's deferred install event - not in lib.dom, and only ever usable once. */
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

type BipWindow = Window & { __ROSA_BIP?: BeforeInstallPromptEvent | null };

/** "prompt" = Chromium will show the real dialog. The rest are browsers that can
    install but expose no API for it, so all we can do is say where the control
    is. Browsers with no install path at all get nothing. */
export type InstallOffer = "prompt" | "ios" | "firefox";

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

/** What (if anything) to offer right now. */
export function installOffer(): InstallOffer | null {
  try {
    if (sessionStorage.getItem(SEEN_KEY) === "1") return null;
  } catch {
    // private mode with storage blocked - offering once per page load is fine
  }
  if (installed()) return null;
  if (deferred()) return "prompt";
  if (iosSafari()) return "ios";
  return firefoxAndroid() ? "firefox" : null;
}

/** Remember that this open has been asked, so a refresh stays quiet. */
export function markInstallSeen(): void {
  try {
    sessionStorage.setItem(SEEN_KEY, "1");
  } catch {
    // ignore - worst case the sheet reappears on the next reload
  }
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
