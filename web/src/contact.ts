/** The one outbound path for anything a user writes to us: Contact Us and per-spot
    Reports both come through here.

    Two hops, fired together:
      - the push API's /contact endpoint STORES the message as a private blob, so it
        survives when mail fails;
      - FormSubmit MAILS it. It has to run in the browser: FormSubmit answers 403 to a
        serverless caller from a datacenter IP whatever headers it sends (measured
        2026-09-03), and it is built for browser forms.
    Neither needs an API key. A caller that gets `false` should offer the mailto: link,
    so a message is never silently lost. */

import { profile } from "./session";

const API = (import.meta.env.VITE_PUSH_API as string | undefined) ?? "";
export const CONTACT_EMAIL = "einhanamer@gmail.com";
const FORM = `https://formsubmit.co/ajax/${encodeURIComponent(CONTACT_EMAIL)}`;
export const MESSAGE_MAX = 2000;

export interface Outbound {
  /** free text - the user's own words, or "" for a report with no note */
  message: string;
  /** "feedback" from Contact Us, "report" from a spot's Report sheet */
  kind: "feedback" | "report";
  /** report only: what the reader picked, and which spot it is about */
  reason?: string;
  spot?: { id: string; name: string; town?: string; lat: number; lon: number };
}

/** The plain-text body. A report leads with the tag, the spot and its coordinates,
    because that is what a human needs to act on it. */
function body(o: Outbound): string {
  const lines: string[] = [];
  if (o.kind === "report") {
    lines.push("[report]");
    if (o.reason) lines.push(`issue: ${o.reason}`);
    if (o.spot) {
      lines.push(`spot: ${o.spot.name}${o.spot.town ? ` (${o.spot.town})` : ""}`);
      lines.push(`id: ${o.spot.id}`);
      lines.push(`coords: ${o.spot.lat.toFixed(5)}, ${o.spot.lon.toFixed(5)}`);
      lines.push(
        `map: https://www.google.com/maps/search/?api=1&query=${o.spot.lat.toFixed(5)},${o.spot.lon.toFixed(5)}`,
      );
    }
    lines.push("");
  }
  if (o.message) lines.push(o.message, "");
  lines.push("---");
  const who = sender();
  if (who) lines.push(`from: ${who.name ? `${who.name} <${who.email}>` : who.email}`);
  lines.push(`page: ${location.hash}`, `ua: ${navigator.userAgent}`);
  return lines.join("\n");
}

/** The signed-in user, so a report or message can be answered. Null when signed
    out or when Google gave no email - nothing is ever asked for. */
function sender(): { email: string; name: string | null } | null {
  const p = profile();
  return p?.email ? { email: p.email, name: p.name } : null;
}

export function mailtoFor(o: Outbound): string {
  const subject = o.kind === "report" ? `Rosa report: ${o.spot?.name ?? "spot"}` : "Rosa feedback";
  return `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body(o))}`;
}

/** Sends both hops. Resolves true when the message is at least safely stored. */
export async function send(o: Outbound): Promise<boolean> {
  const text = body(o);

  const stored = fetch(`${API}/api/contact`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: text,
      kind: o.kind,
      reason: o.reason ?? null,
      spot: o.spot?.id ?? null,
      email: sender()?.email ?? null,
      name: sender()?.name ?? null,
      page: location.hash,
      ua: navigator.userAgent,
    }),
  }).catch(() => null);

  let mailed = false;
  try {
    const res = await fetch(FORM, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        _subject: o.kind === "report" ? `Rosa report: ${o.spot?.name ?? "spot"}` : "Rosa feedback",
        _captcha: "false",
        // signed in: Reply in the mail client answers the surfer directly
        ...(sender() ? { _replyto: sender()!.email, name: sender()!.name ?? "" } : {}),
        message: text,
      }),
    });
    mailed = res.ok && String(((await res.json()) as { success?: unknown }).success) === "true";
  } catch {
    mailed = false;
  }

  const kept = (await stored)?.ok ?? false;
  return mailed || kept;
}
