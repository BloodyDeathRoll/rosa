/** Analytics consent, per device - asked only where the law requires it.

    Outside the EEA/UK participation is not optional: analytics is on from the first load
    and no banner appears. Inside it, GA4 runs in cookieless Consent Mode until the visitor
    accepts - country, screen, events and user properties all still arrive, only the
    identifier linking one visit to the next is missing - and the Vercel counter
    (cookieless by design) counts everyone either way.

    Three states, and the difference matters: "granted" and "denied" are answers the
    visitor gave, `null` is a question never put to them. A stored answer wins everywhere,
    so someone who declines in Berlin stays declined in Bali.

    Stored in localStorage, so it is a per-device answer and a private window is asked
    again. If storage is blocked the answer reads as null every load: inside the zone the
    banner shows each time, which is the conservative failure and not a tracking one. */

import { consentRequiredHere } from "./geoconsent";

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

/** Analytics is on by default everywhere consent is not legally required - the
    measurement is not optional there, and no banner is shown. Inside the EEA/UK it stays
    off until the visitor says otherwise. A stored "denied" is honoured everywhere: once
    someone has actually declined, that answer travels with them. */
export function consentGranted(): boolean {
  const stored = readConsent();
  if (stored !== null) return stored === "granted";
  return !consentRequiredHere();
}

/** Whether to put the question on screen: only where it is legally required AND has
    never been answered. Everywhere else there is nothing to ask. */
export function consentPending(): boolean {
  return readConsent() === null && consentRequiredHere();
}

export function writeConsent(v: Exclude<Consent, null>): void {
  try {
    localStorage.setItem(KEY, v);
  } catch {
    // private mode - the answer does not persist, and the banner asks again next load
  }
}
