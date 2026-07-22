import { useEffect } from "preact/hooks";
import { ChevronLeftIcon } from "../components/icons";
import { signalReady } from "../splash";

export type AboutDoc = "how" | "terms" | "privacy";

const TITLES: Record<AboutDoc, string> = {
  how: "How Rosa works",
  terms: "Terms of Use",
  privacy: "Privacy Policy",
};

function HowItWorks() {
  return (
    <>
      <p class="about-lead">Rosa answers one question: is it worth surfing — and when, and where?</p>
      <p>Here is how, in plain terms:</p>
      <ol class="about-steps">
        <li>
          <b>We start with the forecast.</b> Rosa reads worldwide wave and wind forecasts from
          public weather models — the same kind national weather services rely on. That tells us how
          big the waves out at sea will be, how far apart they roll in, which direction they come
          from, and what the wind is doing.
        </li>
        <li>
          <b>We bring the waves to your beach.</b> Waves out at sea are not the ones that break on
          the sand. For every spot, Rosa looks at the shape of the seabed and which way the beach
          faces, and works out how those waves will actually stand up and break where you surf.
        </li>
        <li>
          <b>We turn it into a score.</b> Every hour gets a rating from 0 to 100. Bigger, cleaner,
          well-lined-up waves with friendly wind score higher; small, messy, or blown-out
          conditions score lower. We boil that down to a single word — from Flat to Epic — so you
          can read it at a glance.
        </li>
        <li>
          <b>We fill in the details.</b> Rosa also shows the tide, the water and air temperature,
          and even suggests which wetsuit to bring.
        </li>
      </ol>
      <p class="about-note">
        Rosa is a forecast, not a live camera. Models are sometimes wrong and the ocean does its
        own thing — always trust your own eyes at the beach. We refresh the forecast several times a
        day, and always show which model it came from and when it last ran, so you know how fresh it
        is.
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
        your safety — always judge the conditions yourself before you enter the water.
      </p>
      <h2>No warranty</h2>
      <p>
        Rosa is provided “as is”, without warranties of any kind. We work hard to be accurate but do
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
      <h2>No account needed</h2>
      <p>
        Rosa does not ask you to sign up, and we do not collect your name, email, or other personal
        details.
      </p>
      <h2>What is stored on your device</h2>
      <p>
        Your preferences — units, theme, and favorite spots — are saved locally in your browser.
        They stay on your device and are not sent to us.
      </p>
      <h2>Location</h2>
      <p>
        If you allow location access, Rosa uses it only to show the spots nearest you. Your location
        is not stored and is not sent to us.
      </p>
      <h2>Hosting</h2>
      <p>
        Rosa is served as static files by our hosting provider, which may keep standard technical
        logs (such as anonymous request data) needed to run the service.
      </p>
      <h2>Third parties</h2>
      <p>
        Forecast data comes from providers such as Open-Meteo, who have their own privacy practices.
      </p>
    </>
  );
}

export function AboutPage({ doc }: { doc: AboutDoc }) {
  // static content — ready as soon as it mounts (lets the splash lift promptly)
  useEffect(signalReady, []);
  return (
    <main class="page about-page">
      <header class="about-head">
        <button
          class="spot-back"
          onClick={() => (location.hash = "#/settings")}
          aria-label="Back to profile"
        >
          <ChevronLeftIcon />
        </button>
        <h1>{TITLES[doc]}</h1>
      </header>
      <div class="about-body">
        {doc === "how" ? <HowItWorks /> : doc === "terms" ? <Terms /> : <Privacy />}
      </div>
    </main>
  );
}
