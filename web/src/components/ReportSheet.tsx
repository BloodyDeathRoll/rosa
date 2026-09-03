import { useEffect, useState } from "preact/hooks";
import { mailtoFor, send, MESSAGE_MAX, type Outbound } from "../contact";

/** Per-spot "Report": the reader picks what is wrong, optionally says more, and it is
    mailed to the maintainer tagged [report] with the spot's name and coordinates.
    Nothing is applied automatically - every report is read by a human first. */

export const REPORT_REASONS = [
  "Wrong location on the map",
  "Wrong spot name",
  "Forecast too high",
  "Forecast too low",
  "Wind is wrong",
  "Camera is offline",
] as const;

type State = "idle" | "sending" | "sent" | "failed";

export function ReportSheet({
  spot,
  onClose,
}: {
  spot: NonNullable<Outbound["spot"]>;
  onClose: () => void;
}) {
  const [reason, setReason] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [state, setState] = useState<State>("idle");

  // Escape closes, and the page behind must not scroll under the sheet
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

  const outbound: Outbound = {
    kind: "report",
    reason: reason ?? undefined,
    message: note.trim(),
    spot,
  };

  const submit = async () => {
    if (!reason || state === "sending") return;
    setState("sending");
    setState((await send(outbound)) ? "sent" : "failed");
  };

  return (
    <div class="sheet-scrim" onClick={onClose}>
      <div
        class="sheet"
        role="dialog"
        aria-modal="true"
        aria-label={`Report an issue with ${spot.name}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div class="sheet-grab" aria-hidden="true" />
        {state === "sent" ? (
          <>
            <h2 class="sheet-title">Thank you</h2>
            <p class="sheet-lead">
              Your report is with us. We read every one by hand before changing anything.
            </p>
            <div class="sheet-actions">
              <button class="sheet-send" onClick={onClose}>
                Done
              </button>
            </div>
          </>
        ) : (
          <>
            <h2 class="sheet-title">Report an issue</h2>
            <p class="sheet-lead">
              {spot.name}
              {spot.town ? ` · ${spot.town}` : ""}
            </p>
            <div class="report-reasons" role="radiogroup" aria-label="What is wrong?">
              {REPORT_REASONS.map((r) => (
                <button
                  key={r}
                  type="button"
                  role="radio"
                  aria-checked={reason === r}
                  class={reason === r ? "report-reason on" : "report-reason"}
                  onClick={() => setReason(r)}
                >
                  {r}
                </button>
              ))}
            </div>
            <textarea
              class="contact-text report-note"
              value={note}
              maxLength={MESSAGE_MAX}
              rows={3}
              placeholder="Anything else? (optional)"
              aria-label="More detail"
              onInput={(e) => setNote((e.currentTarget as HTMLTextAreaElement).value)}
            />
            {state === "failed" && (
              <p class="contact-status contact-failed" role="alert">
                Could not send right now. <a href={mailtoFor(outbound)}>Email it instead</a>.
              </p>
            )}
            <div class="sheet-actions">
              <button class="sheet-cancel" onClick={onClose}>
                Cancel
              </button>
              <button
                class="sheet-send"
                disabled={!reason || state === "sending"}
                onClick={() => void submit()}
              >
                {state === "sending" ? "Sending…" : "Send report"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
