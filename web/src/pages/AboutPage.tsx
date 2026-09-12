import { useEffect, useState } from "preact/hooks";
import { navigate } from "../router";
import { ChevronLeftIcon } from "../components/icons";
import { mailtoFor, send as sendOutbound, MESSAGE_MAX } from "../contact";
import { signalReady } from "../splash";

export type AboutDoc = "how" | "reading" | "terms" | "privacy" | "contact";

const DOCS: Record<AboutDoc, { title: string; img: string }> = {
  how: { title: "How it works", img: "/about/how.jpg" },
  reading: { title: "Reading the forecast", img: "/about/reading.jpg" },
  terms: { title: "Terms of Use", img: "/about/terms.jpg" },
  privacy: { title: "Privacy Policy", img: "/about/privacy.jpg" },
  contact: { title: "Contact Us", img: "/about/contact.jpg" },
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
              <b>NOAA</b> and <b>ECMWF</b> open data directly, for worldwide waves: Rosa reads the
              two global wave models itself, blends them, and takes sea temperature from NOAA too.
            </li>
            <li>
              <b>DWD</b> (the German weather service) open data for each swell's peak period.
            </li>
            <li>
              <b>Open-Meteo</b> for wind and weather.
            </li>
            <li>
              <b>EOT20</b> tide harmonics, so every spot gets a real tide curve for the whole
              forecast.
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
        We refresh the forecast several times a day, and always show when it last ran, so you know
        how fresh it is.
      </p>
    </>
  );
}

/** Glossary for every number the app shows. Written for a surfer, not a forecaster:
    plain words first, the honest caveat second, never a formula. */
function ReadingTheForecast() {
  return (
    <>
      <p class="about-lead">Every number in Rosa, in plain terms.</p>
      <p>
        Nothing here is secret. If a figure looks wrong to you, your eyes win - and we would rather
        you knew exactly what we are claiming than trusted it blindly.
      </p>

      <h2>The word: Flat, Poor, Fair, Good, Epic</h2>
      <p>
        The one-word verdict on each hour, from a score out of 100. Three things feed it: the{" "}
        <b>size</b> of the surf, the <b>period</b> of the swell, and the <b>wind</b>. Good size and
        long period with light or offshore wind scores high; small, short, or blown-out scores low.
      </p>
      <p>
        Wind can only ever <i>polish</i> waves that already exist. A glassy offshore morning with no
        swell stays Poor - it cannot be talked up into Good by the wind alone.
      </p>

      <h2>Surf - the range, and the number under it</h2>
      <p>
        This is the height of the <b>breaking wave at the spot</b>, not the wave height out at sea.
        Rosa takes the open-ocean swell and walks it into the beach over the real shape of the
        seabed, so it grows, bends, and finally breaks the way it actually would there.
      </p>
      <p>
        One honest limit on that. The public seabed maps we use (GEBCO) stop well short of the
        surf zone - at the average spot the shallowest depth they give us is about 7 metres, and
        waves do most of their growing in the last metre or two. So Rosa walks the swell in as far
        as the map goes and then finishes the last stretch with a published formula that predicts
        breaker height from the swell's height, period and angle alone. Until 2 August 2026 it did
        not finish that stretch at all, and every spot read too small as a result.
      </p>
      <p>
        When more than one swell is running, Rosa asks how far apart they are pointing. Swells
        arriving from roughly the same direction are one body of water and their energy adds up.
        Swells crossing from clearly different directions do not: they break at different angles on
        different parts of the beach, and the wave you actually ride belongs to one of them, so the
        bigger one sets the number. Until 3 August 2026 Rosa added every swell together regardless
        of direction, which made busy multi-swell days read too big.
      </p>
      <p>
        We show a range because no forecast is precise to the centimetre. Words like{" "}
        <i>waist-high</i> or <i>overhead</i> are the same number said out loud.
      </p>
      <p>
        The smaller number underneath is a <b>different measurement</b>: the height of that swell
        out in deep water, before it reaches the coast, carrying its unit so you can tell the two
        apart. Either one can be the bigger, and that is not a contradiction. A long-period
        groundswell arrives at the beach <i>taller</i> than it was at sea - it stands up as the
        water shallows, which is why a 1.5 m reading offshore can be well overhead at the reef. A
        short-period wind sea does the opposite and loses most of itself on the way in. Period and
        the angle it meets the coast at decide which happens.
      </p>

      <h2>Swell - where the energy is coming from</h2>
      <p>
        A swell is one train of waves travelling from one storm. There are usually several at once,
        so Rosa lists them separately rather than mashing them into one figure.
      </p>
      <p>
        The direction is where the swell is coming <b>from</b>. Each spot faces a certain way and
        only picks up swell from a band of directions - swell arriving outside that band still shows
        in the list, but it does not count toward the score, because the headland or the coast
        blocks it.
      </p>

      <h2>Period - and why it says 8s when the maths uses 6s</h2>
      <p>
        Period is the gap in seconds between waves, and it matters as much as height: long-period
        swell carries far more energy and stands up taller when it hits shallow water. Short-period
        windswell is weaker than its height suggests.
      </p>
      <p>
        The models publish two of them. The <b>peak period</b> is the dominant rhythm of the swell -
        the number surf reports quote, as in "3ft at 8 seconds". The <b>mean period</b> is the
        average across the whole sea state, and it always reads lower because short, choppy waves
        drag it down.
      </p>
      <p>
        Rosa <b>displays the peak period</b>, because that is the convention you already know and
        the honest description of the swell. As of 30 July 2026 the <b>surf height is judged on the
        peak period too</b>: we used to rate how rideable a swell was from the mean period, and it
        under-called real Mediterranean surf by up to double against what we saw in the water.
        Two smaller pieces still run on the mean period - the arithmetic that bends waves as they
        shoal in, and the Period bar on the rating card - so the seconds on screen can still sit a
        little above some of the seconds doing the work. We would rather show you the number
        surfers use and say this plainly than quietly show the lower one.
      </p>

      <h2>Wind</h2>
      <p>
        Shown in knots, with the direction it is blowing <b>from</b>, and a word for what that means
        at this particular spot:
      </p>
      <ul class="about-sub">
        <li>
          <b>Offshore</b> - blowing from the land out to sea. Holds the wave face up and grooms it.
          The good one.
        </li>
        <li>
          <b>Cross-shore</b> - along the beach. Tolerable when light, messy when not.
        </li>
        <li>
          <b>Onshore</b> - blowing in from the sea. Crumbles the waves and turns the surface to
          chop.
        </li>
      </ul>
      <p>
        The same wind direction is offshore at one beach and onshore at the next, so the word is
        worked out per spot, not per region.
      </p>

      <h2>kJ - how much punch the swell carries</h2>
      <p>
        Wave energy, in kilojoules per metre of wave crest. Height alone does not tell you whether a
        swell is serious: energy grows with the <i>square</i> of the height and the{" "}
        <i>square</i> of the period, so a long-period swell can carry several times the punch of a
        wind chop of the same height.
      </p>
      <p>
        Use it to compare days. Two mornings both listed at chest-high are not the same session if
        one reads 40 kJ and the other 300 kJ. Only swell the spot actually faces is counted.
      </p>

      <h2>hPa - air pressure</h2>
      <p>
        Sea-level air pressure, the same units a barometer uses. It is a weather signal, not a surf
        one: falling pressure means a system moving in - wind and, a day or two later, swell.
        Steady high pressure usually means settled, lighter mornings.
      </p>

      <h2>Water and air temperature, and the wetsuit</h2>
      <p>
        The wetsuit suggestion comes from the water temperature alone, using the industry-standard
        bands. It is a starting point - if you run cold, or the wind is up, go thicker.
      </p>

      <h2>Tide</h2>
      <p>
        The height of the water against its average level, hour by hour, with the high and low
        marked, for the full forecast - even two weeks out. This is the <b>astronomical</b> tide,
        computed from each spot's own harmonic constants (the same maths behind a printed tide
        table). It does not include what the weather pushes on top - storm surge can sit above or
        below it by a few tens of centimetres.
      </p>
      <p>
        How much it matters depends entirely on where you are. On the Mediterranean the tide moves
        maybe fifteen centimetres and is barely worth a glance. In Costa Rica it swings a metre and
        a half or more, and it changes everything.
      </p>

      <h2>Light</h2>
      <p>
        First light, sunrise, sunset and last light for that spot's own date and location. First and
        last light are the useful ones - you can usually surf a good half hour before the sun is up.
      </p>

      <h2>Confidence, and how fresh this is</h2>
      <p>
        Rosa runs several times a day and always shows when it last ran. Confidence reflects two
        things: how far ahead the forecast is looking, and how much the
        different weather models agree with each other right now. Tomorrow is worth trusting; day
        twelve is a hint about a trend, nothing more.
      </p>

      <h2>The day strip and the three bars</h2>
      <p>
        Each day shows its best few hours as coloured bars, so you can find the good day without
        opening every one. The Size, Period and Wind bars break the chosen day's rating into its
        three ingredients - a quick way to see <i>why</i> a day scored what it did, and which of the
        three is letting it down.
      </p>
      <p>
        Day ratings only count daylight hours. A perfect 3am is not a session.
      </p>

      <h2>Colours</h2>
      <p>
        The coloured rail down the left of each hour is the rating, in visual form - the same scale
        as the words, so you can scan a day without reading a single number.
      </p>

      <h2>Units</h2>
      <p>
        Metres or feet, and Celsius or Fahrenheit, are yours to set in Profile. Wind is always in
        knots and period always in seconds, because that is what surf forecasts everywhere use.
      </p>

      <h2>Swell alerts</h2>
      <p>
        If you turn them on, Rosa notifies you when a real swell is lining up for a spot you follow
        - a sustained run of well-above-normal energy that peaks at Good or better. One swell gets
        one notification, not one per spot per hour.
      </p>

      <h2>What Rosa does not know</h2>
      <p>
        It does not know the sandbank shifted last week, that the river mouth is closed out, that
        the car park fills at seven, or that the peak works on a dropping tide only. Local knowledge
        beats every model, including ours.
      </p>
      <p class="about-note">
        Forecasts are estimates. Check the conditions with your own eyes before you paddle out, and
        never let a green number talk you into water you would not otherwise enter.
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
      <p class="about-muted">Last updated: September 2026</p>
      <p>
        Rosa is built to respect your privacy. In short: we keep only what the app needs to work
        for you, and you can delete it at any time.
      </p>
      <h2>What is stored on your device</h2>
      <p>
        Your preferences, units, theme, recent spots, and a copy of your favorite spots are saved
        locally in your browser.
      </p>
      <h2>Your account</h2>
      <p>
        Saving favorite spots needs a Rosa account, which you create by signing in with Google.
        We store the name, email address, and profile picture Google shares, your list of favorite
        spots, and when you last used Rosa. We use them only to keep your favorites in sync across
        your devices and to count how many people use Rosa. Nothing is sold or shared. The data
        lives on Cloudflare's servers. Profile › Account › Delete account removes all of it.
      </p>
      <h2>Notifications and feedback</h2>
      <p>
        If you turn on swell alerts, your browser's push address, your favorite spot ids, and the id
        of the spot nearest you are stored so we can send the alert. They are deleted when you turn
        alerts off. If you answer a "was the call right?" question, the spot, date, and your answer
        are stored to tune the forecast. Contact and report messages are stored so we can read them.
      </p>
      <h2>Location</h2>
      <p>
        If you allow location access, Rosa uses it only to show the spots nearest you. Your location
        is not stored and is not sent to us; only the id of the nearest spot is, as above.
      </p>
      <h2>Analytics</h2>
      <p>
        We count visits and page views with Vercel Web Analytics, which does not use cookies and does
        not identify you.
      </p>
      <p>
        We also use Google Analytics to see which spots and screens get used, and roughly where in
        the world Rosa is being opened. It records the screen you are on, the spot you opened and its
        region, and settings like your units and theme. It never receives your name, email address,
        or anything else that identifies you, and Rosa runs no advertising.
      </p>
      <p>
        If you are in the EU, the EEA or the UK we ask first, and until you say yes Google
        Analytics runs without cookies and without any identifier - we see a country and a screen,
        and nothing that follows you between visits. Elsewhere it runs as part of the app. Either
        way it never receives anything that identifies you, and if you decline, that answer is
        remembered on this device and applies wherever you travel.
      </p>
      <h2>Third-party services</h2>
      <p>
        Rosa is built on open data and services from these providers, each with their own privacy
        practices:
      </p>
      <ul class="about-links">
        <li>
          <a href="https://open-meteo.com" target="_blank" rel="noopener noreferrer">Open-Meteo</a> ·
          wave and weather forecasts (CC-BY 4.0)
        </li>
        <li>
          <a href="https://www.ecmwf.int/en/forecasts/datasets/open-data" target="_blank" rel="noopener noreferrer">ECMWF open data</a> ·
          wave spectra and forecasts (CC-BY 4.0)
        </li>
        <li>
          <a href="https://www.noaa.gov" target="_blank" rel="noopener noreferrer">NOAA</a> ·
          wave forecasts, sea temperature, and buoy observations
        </li>
        <li>
          <a href="https://doi.org/10.17882/79489" target="_blank" rel="noopener noreferrer">EOT20</a> ·
          tide model (Hart-Davis et al., SEANOE, CC-BY 4.0)
        </li>
        <li>
          <a href="https://www.gebco.net" target="_blank" rel="noopener noreferrer">GEBCO</a> ·
          seabed depth data
        </li>
        <li>
          <a href="https://openfreemap.org" target="_blank" rel="noopener noreferrer">OpenFreeMap</a>
          · map background tiles, © <a href="https://openmaptiles.org" target="_blank" rel="noopener noreferrer">OpenMapTiles</a>
        </li>
        <li>
          <a href="https://vercel.com" target="_blank" rel="noopener noreferrer">Vercel</a> ·
          hosting and visit counts
        </li>
        <li>
          <a href="https://www.cloudflare.com" target="_blank" rel="noopener noreferrer">Cloudflare</a> ·
          account and favorites storage
        </li>
        <li>
          <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">Google</a> ·
          sign-in and analytics
        </li>
      </ul>
    </>
  );
}

/** Contact Us: one text block and a Send button. Delivery lives in ../contact - the
    same path a per-spot Report takes. */

function ContactUs() {
  const [text, setText] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "failed">("idle");

  const submit = async () => {
    const message = text.trim();
    if (!message || state === "sending") return;
    setState("sending");
    const ok = await sendOutbound({ kind: "feedback", message });
    setState(ok ? "sent" : "failed");
    if (ok) setText("");
  };

  const mailto = mailtoFor({ kind: "feedback", message: text });

  return (
    <>
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
            void submit();
          }}
        >
          <textarea
            class="contact-text"
            value={text}
            maxLength={MESSAGE_MAX}
            rows={7}
            placeholder="What's on your mind?"
            aria-label="Your message"
            onInput={(e) => setText((e.currentTarget as HTMLTextAreaElement).value)}
          />
          <div class="contact-actions">
            <button type="submit" class="contact-send" disabled={!text.trim() || state === "sending"}>
              {state === "sending" ? "Sending…" : "Send"}
            </button>
          </div>
          {state === "failed" && (
            <p class="contact-status contact-failed" role="alert">
              Could not send right now. <a href={mailto}>Email us instead</a> - your message is kept
              in the link.
            </p>
          )}
        </form>
      )}
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
          onClick={() => (navigate("/settings"))}
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
        {doc === "how" ? (
          <HowItWorks />
        ) : doc === "reading" ? (
          <ReadingTheForecast />
        ) : doc === "terms" ? (
          <Terms />
        ) : doc === "privacy" ? (
          <Privacy />
        ) : (
          <ContactUs />
        )}
      </div>
    </main>
  );
}
