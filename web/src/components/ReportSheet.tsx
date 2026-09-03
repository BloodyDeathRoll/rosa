import { useEffect, useState } from "preact/hooks";
import { ChevronLeftIcon } from "./icons";
import { mailtoFor, send, MESSAGE_MAX, type Outbound } from "../contact";

/** Per-spot "Report", a full screen of its own.

    Deliberately NOT a bottom sheet: the app's surfaces are translucent by design
    (--background is 11% white over a photographic backdrop), so a sheet let the whole
    forecast bleed through and was unreadable. This paints --body-bg, the one opaque
    token, edge to edge.

    Reasons are checkboxes, not one-of: a pin can be wrong AND the wind can be off, and
    making the reader send two reports for that loses information. Anything the list
    cannot express goes in the note, which becomes REQUIRED when "Something else" is
    ticked - that is the one case where the text is the whole report. */

export const REPORT_REASONS = [
  "Wrong location on the map",
  "Wrong spot name",
  "Forecast too high",
  "Forecast too low",
  "Wind is wrong",
  "Camera is offline",
] as const;

const OTHER = "Something else";

type State = "idle" | "sending" | "sent" | "failed";

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
      <path
        d="M5 13l4 4L19 7"
        fill="none"
        stroke="currentColor"
        stroke-width="3"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  );
}

export function ReportSheet({
  spot,
  onClose,
}: {
  spot: NonNullable<Outbound["spot"]>;
  onClose: () => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [state, setState] = useState<State>("idle");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const toggle = (r: string) =>
    setPicked((p) => (p.includes(r) ? p.filter((x) => x !== r) : [...p, r]));

  const needsNote = picked.includes(OTHER);
  const trimmed = note.trim();
  const ready = picked.length > 0 && (!needsNote || trimmed.length > 0);

  const outbound: Outbound = {
    kind: "report",
    reason: picked.join("; "),
    message: trimmed,
    spot,
  };

  const submit = async () => {
    if (!ready || state === "sending") return;
    setState("sending");
    setState((await send(outbound)) ? "sent" : "failed");
  };

  return (
    <main class="page report-page" role="dialog" aria-modal="true" aria-label="Report an issue">
      <header class="report-head">
        <button class="report-back" onClick={onClose} aria-label="Close">
          <ChevronLeftIcon />
        </button>
        <b>Report an issue</b>
      </header>

      {state === "sent" ? (
        <div class="report-body">
          <h1 class="report-title">Thank you</h1>
          <p class="report-lead">
            Your report is with us. We read every one by hand, and nothing changes on the map
            until someone has.
          </p>
          <div class="report-foot">
            <button class="report-send" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <div class="report-body">
          <h1 class="report-title">{spot.name}</h1>
          <p class="report-lead">
            {spot.town ? `${spot.town} · ` : ""}
            {spot.lat.toFixed(4)}, {spot.lon.toFixed(4)}
          </p>

          <p class="report-q">What is wrong? Tick everything that applies.</p>
          <div class="report-list">
            {[...REPORT_REASONS, OTHER].map((r) => {
              const on = picked.includes(r);
              return (
                <button
                  key={r}
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  class={on ? "report-row on" : "report-row"}
                  onClick={() => toggle(r)}
                >
                  <span class="report-box" aria-hidden="true">
                    {on && <CheckIcon />}
                  </span>
                  <span class="report-label">{r}</span>
                </button>
              );
            })}
          </div>

          <label class="report-note-label" for="report-note">
            {needsNote ? "Tell us what is wrong" : "Anything else? (optional)"}
          </label>
          <textarea
            id="report-note"
            class="contact-text report-note"
            value={note}
            maxLength={MESSAGE_MAX}
            rows={4}
            placeholder={needsNote ? "What did you see?" : "Optional"}
            onInput={(e) => setNote((e.currentTarget as HTMLTextAreaElement).value)}
          />

          {state === "failed" && (
            <p class="contact-status contact-failed" role="alert">
              Could not send right now. <a href={mailtoFor(outbound)}>Email it instead</a>.
            </p>
          )}

          <div class="report-foot">
            <button class="report-send" disabled={!ready || state === "sending"} onClick={() => void submit()}>
              {state === "sending" ? "Sending…" : "Send report"}
            </button>
            <p class="report-fine">Reviewed by a person before anything changes.</p>
          </div>
        </div>
      )}
    </main>
  );
}
