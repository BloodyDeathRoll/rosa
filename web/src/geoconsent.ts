/** Where consent is legally required, decided from the device's own timezone.

    Rosa is a static site with no server to read a request's country from, and asking a
    geo-IP service would cost a request on the critical path and hand a third party every
    visitor's address. `Intl.DateTimeFormat().resolvedOptions().timeZone` costs nothing,
    works offline, needs no permission and never leaves the device.

    It is a proxy, not a border: a VPN, a traveller, or a wrong clock will misplace
    someone. So the failure is deliberately one-sided - anything unreadable or unknown
    counts as inside the zone and gets asked. Over-asking is a worse product and a fine
    legal outcome; under-asking is the reverse.

    Listed: the EU 27, the rest of the EEA (Iceland, Liechtenstein, Norway), the UK, and
    Switzerland - whose FADP consent rules are close enough that the distinction is not
    worth a second code path. Includes the outermost regions and dependencies that carry
    EU law with them (Canaries, Azores, Madeira, Reunion, Martinique, Guadeloupe,
    Cayenne, Mayotte), which a "Europe/" prefix test would miss. */

const CONSENT_ZONES = new Set([
  // EU 27
  "Europe/Vienna", "Europe/Brussels", "Europe/Sofia", "Europe/Zagreb", "Asia/Nicosia",
  "Europe/Nicosia", "Europe/Prague", "Europe/Copenhagen", "Europe/Tallinn",
  "Europe/Helsinki", "Europe/Paris", "Europe/Berlin", "Europe/Busingen",
  "Europe/Athens", "Europe/Budapest", "Europe/Dublin", "Europe/Rome", "Europe/Riga",
  "Europe/Vilnius", "Europe/Luxembourg", "Europe/Malta", "Europe/Amsterdam",
  "Europe/Warsaw", "Europe/Lisbon", "Europe/Bucharest", "Europe/Bratislava",
  "Europe/Ljubljana", "Europe/Madrid", "Europe/Stockholm",
  // EU outermost regions and territories that carry EU law
  "Atlantic/Canary", "Atlantic/Azores", "Atlantic/Madeira", "Africa/Ceuta",
  "Indian/Reunion", "Indian/Mayotte", "America/Martinique", "America/Guadeloupe",
  "America/Cayenne", "America/Miquelon",
  // rest of the EEA, the UK, Switzerland
  "Atlantic/Reykjavik", "Europe/Vaduz", "Europe/Oslo", "Arctic/Longyearbyen",
  "Europe/London", "Europe/Belfast", "Europe/Guernsey", "Europe/Isle_of_Man",
  "Europe/Jersey", "Europe/Gibraltar", "Europe/Zurich",
]);

/** True where a cookie needs asking for. Unknown reads as true - see the note above. */
export function consentRequiredHere(): boolean {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!tz) return true;
    if (CONSENT_ZONES.has(tz)) return true;
    // An unrecognised Europe/* zone is either a new name for a listed country or a
    // non-EU European one; ask rather than guess which.
    return tz.startsWith("Europe/");
  } catch {
    return true;
  }
}
