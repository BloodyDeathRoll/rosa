import { useEffect } from "preact/hooks";
import { ChevronLeftIcon } from "../components/icons";
import { signalReady } from "../splash";

export type AboutDoc = "how" | "terms" | "privacy";

const DOCS: Record<AboutDoc, { title: string; img: string }> = {
  how: { title: "How it works", img: "/about/how.jpg" },
  terms: { title: "Terms of Use", img: "/about/terms.jpg" },
  privacy: { title: "Privacy Policy", img: "/about/privacy.jpg" },
};

function HowItWorks() {
  return (
    <>
      <p class="about-lead">Rosa answers one question: is it worth surfing, and when, and where?</p>
      <p>Here is how, in plain terms.</p>
      <ol class="about-steps">
        <li>
          <b>We start with free, public forecasts.</b> Rosa is built on open data that anyone can
          use:
          <ul class="about-sub">
            <li>
              <b>Open-Meteo</b> for worldwide waves and wind (it blends the big global models like
              ECMWF and NOAA).
            </li>
            <li>
              <b>GEBCO</b> for the shape of the seabed near each spot.
            </li>
            <li>
              Public surf buoys (<b>NDBC</b> and <b>ISRAMAR</b>) to check our forecasts against what
              the ocean actually did.
            </li>
          </ul>
        </li>
        <li>
          <b>We do the maths for every spot, ahead of time.</b> A few times a day, Rosa takes those
          forecasts and, for each surf spot, works out how the open-ocean waves will actually stand
          up and break there, using the seabed shape and the way the beach faces. It saves the
          result, so the app opens instantly and still works on a shaky signal.
        </li>
        <li>
          <b>We turn it into a score.</b> Every hour gets a rating from 0 to 100. Bigger, cleaner,
          well-lined-up waves with friendly wind score higher; small, messy, or blown-out
          conditions score lower. We boil that down to a single word, from Flat to Epic, so you can
          read it at a glance.
        </li>
      </ol>
      <p class="about-note">
        We refresh the forecast several times a day, and always show which model it came from and
        when it last ran, so you know how fresh it is.
      </p>
    </>
  );
}

function Terms() {
  return (
    <>
      <p class="about-muted">Last updated: July 2026</p>
      <p>Welcome to Rosa. By using the app, you agree to the following.</p>
      <h2>Informational use only</h2>
      <p>
        Rosa provides surf forecasts and related information for general, informational purposes.
        Forecasts are estimates and can be wrong. Never rely on Rosa alone for decisions that affect
        your safety. Always judge the conditions yourself before you enter the water.
      </p>
      <h2>No warranty</h2>
      <p>
        Rosa is provided "as is", without warranties of any kind. We work hard to be accurate but do
        not guarantee it, and we are not responsible for any loss, injury, or damage that results
        from using the app.
      </p>
      <h2>Fair use</h2>
      <p>Please use Rosa lawfully, and do not attempt to disrupt, overload, or misuse the service.</p>
      <h2>Data sources</h2>
      <p>
        Rosa is built on public weather and ocean data from third parties, including Open-Meteo.
        Their terms and attribution requirements apply to that data.
      </p>
      <h2>Changes</h2>
      <p>Rosa is under active development. We may update the app or these terms at any time.</p>
    </>
  );
}

function Privacy() {
  return (
    <>
      <p class="about-muted">Last updated: July 2026</p>
      <p>Rosa is built to respect your privacy. In short: your data stays on your device.</p>
      <h2>What is stored on your device</h2>
      <p>
        Your preferences, units, theme, and favorite spots are saved locally in your browser. They
        stay on your device and are not sent to us.
      </p>
      <h2>Location</h2>
      <p>
        If you allow location access, Rosa uses it only to show the spots nearest you. Your location
        is not stored and is not sent to us.
      </p>
      <h2>Third-party services</h2>
      <p>
        Rosa is built on open data and services from these providers, each with their own privacy
        practices:
      </p>
      <ul class="about-links">
        <li>
          <a href="https://open-meteo.com" target="_blank" rel="noopener noreferrer">Open-Meteo</a> ·
          wave and weather forecasts
        </li>
        <li>
          <a href="https://www.gebco.net" target="_blank" rel="noopener noreferrer">GEBCO</a> ·
          seabed depth data
        </li>
        <li>
          <a href="https://carto.com" target="_blank" rel="noopener noreferrer">CARTO</a> · map
          background tiles
        </li>
        <li>
          <a href="https://vercel.com" target="_blank" rel="noopener noreferrer">Vercel</a> ·
          hosting
        </li>
      </ul>
    </>
  );
}

export function AboutPage({ doc }: { doc: AboutDoc }) {
  // static content, ready as soon as it mounts (lets the splash lift promptly)
  useEffect(signalReady, []);
  const { title, img } = DOCS[doc];
  return (
    <main class="page about-page">
      <div class="about-hero" style={`background-image:url(${img})`}>
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
          <h1 class="about-hero-title">{title}</h1>
        </div>
      </div>
      <div class="about-body">
        {doc === "how" ? <HowItWorks /> : doc === "terms" ? <Terms /> : <Privacy />}
      </div>
    </main>
  );
}
