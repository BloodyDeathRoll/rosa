/** Build-time entry (`vite build --ssr`, see scripts/prerender.mjs): renders the
    static About pages to HTML so the prerendered shells carry their real text
    for crawlers. Nothing here ships to the browser. */
import { render } from "preact-render-to-string";
import { AboutPage, type AboutDoc } from "./pages/AboutPage";

export function renderAbout(doc: AboutDoc): string {
  return render(<AboutPage doc={doc} />);
}
