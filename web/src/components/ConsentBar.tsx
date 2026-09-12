import { useEffect, useState } from "preact/hooks";
import { consentPending, writeConsent } from "../consent";
import { gaDenyConsent, gaEnabled, gaGrantConsent } from "../ga";

/** The analytics question, asked once per device and only where it is required.

    Rendered when GA is configured, the visitor is in the EEA/UK (by timezone - see
    geoconsent.ts), and the question has never been answered. Everywhere else analytics
    is simply part of the app and this never appears. Where it does appear, declining is
    a real choice and not a dark pattern: both buttons are the same size and either
    answer is remembered.

    Bottom of the screen, above the nav, in the same card language as the rest of
    the app. It does not block the forecast - the whole point of Rosa is a
    twenty-second check, and a modal over that would be worse than losing the
    measurement. */
export function ConsentBar() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (gaEnabled() && consentPending()) setOpen(true);
  }, []);

  if (!open) return null;

  const answer = (granted: boolean) => {
    writeConsent(granted ? "granted" : "denied");
    if (granted) gaGrantConsent();
    else gaDenyConsent();
    setOpen(false);
  };

  return (
    <div class="consent-bar" role="dialog" aria-labelledby="consent-title">
      <div class="consent-text">
        <b id="consent-title">Help us make Rosa better?</b>
        <small>
          We count which spots and screens get used. No ads, nothing sold.{" "}
          <a href="/about/privacy">How we handle your data</a>
        </small>
      </div>
      <div class="consent-actions">
        <button class="consent-no" onClick={() => answer(false)}>
          No thanks
        </button>
        <button class="consent-yes" onClick={() => answer(true)}>
          Sure
        </button>
      </div>
    </div>
  );
}
