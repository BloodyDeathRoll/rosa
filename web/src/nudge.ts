/** The "report a spot" nudge: a full-screen note that says the spot page has a
    Report an issue button and a person reads every report. It shows on the
    first launch on a device (install) and on every sign-in, then again once a
    week for four weeks after that, so a new user meets it five times at most
    per install or sign-in. Answered by X or OK; both only close it - the
    schedule is by time, not by whether it was read. State lives in localStorage
    (per device); private mode with storage blocked shows it once per page load. */

const KEY = "rosa.nudge.report";
export const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
/** the first showing plus this many weekly repeats */
export const REPEATS = 4;
/** a sign-in right after the install showing does not show it a second time */
const RECENT_MS = 10 * 60 * 1000;

interface NudgeState {
  started: number; // ms - the install or sign-in that began this run
  shown: number; // showings in this run, the first included
  last: number; // ms - the most recent showing
}

function read(): NudgeState | null {
  try {
    const raw = localStorage.getItem(KEY);
    const s: unknown = raw ? JSON.parse(raw) : null;
    if (!s || typeof s !== "object") return null;
    const { started, shown, last } = s as NudgeState;
    return typeof started === "number" && typeof shown === "number" && typeof last === "number"
      ? { started, shown, last }
      : null;
  } catch {
    return null;
  }
}

function write(s: NudgeState): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // private mode - it shows again next load, which is the best we can do
  }
}

/** Whether the nudge is due right now, unprompted: never shown on this device,
    or a week past the last showing with repeats left in the run. */
export function nudgeDue(now = Date.now()): boolean {
  const s = read();
  if (!s) return true;
  return s.shown <= REPEATS && now - s.last >= WEEK_MS;
}

/** Whether a sign-in should show it: always, unless it was on screen minutes ago
    (a first launch that went straight into sign-in). */
export function nudgeDueOnSignIn(now = Date.now()): boolean {
  const s = read();
  return !s || now - s.last >= RECENT_MS;
}

/** Record a showing. A sign-in starts the run over, an unprompted showing counts
    against the current one. */
export function markNudgeShown(reason: "launch" | "signin", now = Date.now()): void {
  const s = read();
  if (!s || reason === "signin") write({ started: now, shown: 1, last: now });
  else write({ started: s.started, shown: s.shown + 1, last: now });
}
