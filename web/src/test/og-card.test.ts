import { describe, expect, it } from "vitest";
import { cardWhere, escXml, fitLine, fitName, ogCardSvg, textEm } from "../ogCard";
import { spotHead } from "../head";

const MARK = { d: "M0,0L10,10Z", viewBox: "0 0 762.6 828.1" };

describe("share card template", () => {
  it("escapes every XML-special character in names", () => {
    expect(escXml(`Chapman's <Pool> & "Co"`)).toBe("Chapman&apos;s &lt;Pool&gt; &amp; &quot;Co&quot;");
    const svg = ogCardSvg({ name: "A&B <x>", town: "O'Neill", region: "Q" }, MARK);
    expect(svg).toContain("A&amp;B &lt;x&gt;");
    expect(svg).toContain("O&apos;Neill, Q");
    expect(svg).not.toMatch(/<x>/);
  });

  it("keeps a short name on one line at full size", () => {
    expect(fitName("Beit Yanai")).toEqual({ size: 96, lines: ["Beit Yanai"] });
  });

  it("wraps or shrinks a long name into at most two lines that fit", () => {
    for (const name of ["Waikiki Beach Cape Disappointment", "Praia do Forte de São João da Barra Norte Extremo Sul"]) {
      const { size, lines } = fitName(name);
      expect(lines.length).toBeLessThanOrEqual(2);
      for (const l of lines) expect(textEm(l, true) * size).toBeLessThanOrEqual(1200 - 128);
    }
  });

  it("ellipsises a 'town, region' line too long for the card", () => {
    const long = "São João da Barra de Itapemirim Velha do Norte Extremo, Espirito Santo do Brasil";
    const fitted = fitLine(long, 38, false);
    expect(fitted.endsWith("…")).toBe(true);
    expect(textEm(fitted, false) * 38).toBeLessThanOrEqual(1200 - 128);
  });

  it("skips a town or region that repeats the name, like spotHead", () => {
    expect(cardWhere({ name: "Hobe Sound", town: "Hobe Sound", region: "South Florida" })).toBe("South Florida");
    expect(cardWhere({ name: "Þorlákshöfn" })).toBe("");
  });

  it("points a spot page's share image at its build-time card", () => {
    const h = spotHead({ id: "chapman-s-pool", name: "Chapman's Pool", region: "England South", lat: 50.6, lon: -2.06 });
    expect(h.image).toEqual({ url: "https://rosa.surf/og/spot/chapman-s-pool.jpg", alt: "Chapman's Pool surf forecast on Rosa" });
  });
});
