import { useEffect, useState } from "preact/hooks";
import { ChevronLeftIcon } from "../components/icons";
import { signalReady } from "../splash";

/** Contact Us: one text block and a Send button. The message goes to the push API's
    /contact endpoint, which emails it to the maintainer; if the API is unreachable the
    page falls back to a mailto: link so the message is never lost. */

const API = (import.meta.env.VITE_PUSH_API as string | undefined) ?? "";
const CONTACT_EMAIL = "einhanamer@gmail.com";
const MAX = 2000;

type State = "idle" | "sending" | "sent" | "failed";

export function ContactPage() {
  useEffect(signalReady, []);
  const [text, setText] = useState("");
  const [state, setState] = useState<State>("idle");

  const send = async () => {
    const message = text.trim();
    if (!message || state === "sending") return;
    setState("sending");
    try {
      const res = await fetch(`${API}/api/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, page: location.hash, ua: navigator.userAgent }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setState("sent");
      setText("");
    } catch {
      setState("failed");
    }
  };

  const mailto = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("Rosa feedback")}&body=${encodeURIComponent(text)}`;

  return (
    <main class="page about-page contact-page">
      <div class="about-hero" style="background-image:url(/about/contact.jpg)">
        <button
          class="about-back"
          onClick={() => (location.hash = "#/settings")}
          aria-label="Back to profile"
        >
          <ChevronLeftIcon />
        </button>
        <div class="about-hero-cap">
          <div class="about-hero-brand">
            <img class="about-hero-logo" src="/favicon.svg" alt="" />
            <span class="about-hero-word">
              rosa<span class="about-hero-dot" aria-hidden="true" />
            </span>
          </div>
          <h1 class="about-hero-title">Contact Us</h1>
        </div>
      </div>
      <div class="about-body">
        <p class="about-lead">We would love your feedback!</p>
        {state === "sent" ? (
          <p class="contact-status" role="status">
            Sent. Thank you!
          </p>
        ) : (
          <form
            class="contact-form"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <textarea
              class="contact-text"
              value={text}
              maxLength={MAX}
              rows={7}
              placeholder="What's on your mind?"
              aria-label="Your message"
              onInput={(e) => setText((e.currentTarget as HTMLTextAreaElement).value)}
            />
            <div class="contact-actions">
              <button
                type="submit"
                class="contact-send"
                disabled={!text.trim() || state === "sending"}
              >
                {state === "sending" ? "Sending…" : "Send"}
              </button>
            </div>
            {state === "failed" && (
              <p class="contact-status contact-failed" role="alert">
                Could not send right now.{" "}
                <a href={mailto}>Email us instead</a> - your message is kept in the link.
              </p>
            )}
          </form>
        )}
      </div>
    </main>
  );
}
