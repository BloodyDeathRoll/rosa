/** Analytics consent, per device.

    Three states, and the difference matters: "granted" and "denied" are answers,
    `null` is a question not yet asked. GA4 runs in cookieless Consent Mode while the
    answer is null or denied - country, screen and events still arrive, no identifier
    does - so declining costs Rosa the cross-session view and nothing else, and the
    Vercel counter (cookieless by design) keeps counting either way.

    Stored in localStorage, so it is a per-device answer and a private window is asked
    again. If storage is blocked the answer reads as null every load: the banner shows
    each time, which is the conservative failure and not a tracking one. */

const KEY = "rosa.consent.analytics";

export type Consent = "granted" | "denied" | null;

export function readConsent(): Consent {
  try {
    const v = localStorage.getItem(KEY);
    return v === "granted" || v === "denied" ? v : null;
  } catch {
    return null;
  }
}

export function consentGranted(): boolean {
  return readConsent() === "granted";
}

/** Whether to put the question on screen: only when it has never been answered. */
export function consentPending(): boolean {
  return readConsent() === null;
}

export function writeConsent(v: Exclude<Consent, null>): void {
  try {
    localStorage.setItem(KEY, v);
  } catch {
    // private mode - the answer does not persist, and the banner asks again next load
  }
}
