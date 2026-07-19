/** Sunrise/sunset + civil twilight, computed client-side (standard NOAA/astronomical
    formulas — the pipeline doesn't publish sun times yet). Accuracy ±1–2 min. */

const DAY_MS = 86_400_000;
const J1970 = 2440588;
const J2000 = 2451545;
const RAD = Math.PI / 180;
const OBLIQUITY = RAD * 23.4397;

const toJulian = (date: Date) => date.valueOf() / DAY_MS - 0.5 + J1970;
const fromJulian = (j: number) => new Date((j + 0.5 - J1970) * DAY_MS);

const solarMeanAnomaly = (d: number) => RAD * (357.5291 + 0.98560028 * d);

function eclipticLongitude(M: number): number {
  const C = RAD * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M));
  const P = RAD * 102.9372; // perihelion of the Earth
  return M + C + P + Math.PI;
}

const declination = (L: number) => Math.asin(Math.sin(L) * Math.sin(OBLIQUITY));

function hourAngle(h: number, phi: number, dec: number): number {
  const cosH =
    (Math.sin(h) - Math.sin(phi) * Math.sin(dec)) / (Math.cos(phi) * Math.cos(dec));
  return Math.acos(Math.min(1, Math.max(-1, cosH)));
}

export interface SunTimes {
  firstLight: Date; // civil dawn (-6°)
  sunrise: Date; // -0.833°
  sunset: Date;
  lastLight: Date; // civil dusk
}

/** Sun times for the civil date containing `noonUtc` at lat/lon. */
export function sunTimes(noonUtc: Date, lat: number, lon: number): SunTimes {
  const lw = RAD * -lon;
  const phi = RAD * lat;
  const d = toJulian(noonUtc) - J2000;
  const n = Math.round(d - 0.0009 - lw / (2 * Math.PI));
  const ds = 0.0009 + lw / (2 * Math.PI) + n;
  const M = solarMeanAnomaly(ds);
  const L = eclipticLongitude(M);
  const dec = declination(L);
  const Jnoon = J2000 + ds + 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * L);

  const setAt = (angleDeg: number) => {
    const w = hourAngle(RAD * angleDeg, phi, dec);
    return Jnoon + w / (2 * Math.PI);
  };
  const riseAt = (angleDeg: number) => Jnoon - (setAt(angleDeg) - Jnoon);

  return {
    firstLight: fromJulian(riseAt(-6)),
    sunrise: fromJulian(riseAt(-0.833)),
    sunset: fromJulian(setAt(-0.833)),
    lastLight: fromJulian(setAt(-6)),
  };
}

/** "05:52" in the spot's timezone. */
export function fmtClock(date: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  }).format(date);
}
