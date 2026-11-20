export const ESG_PREF = "ESG";
const MARKET = "Marché géographique : ";
export const MARKETS = ["Canada", "États-Unis"] as const;
export type Market = (typeof MARKETS)[number];
export type EsgMarketChoice = { esg: boolean; markets: Market[] };
export const EMPTY_ESG_MARKET: EsgMarketChoice = { esg: false, markets: [] };

const MARKET_EN: Record<Market, string> = { Canada: "Canada", "États-Unis": "United States" };
export const marketName = (m: Market, lang: "fr" | "en") => (lang === "en" ? MARKET_EN[m] : m);

export const ESG_ANSWERS: { value: boolean; label: string; en: string }[] = [
  { value: true, label: "Oui", en: "Yes" },
  { value: false, label: "Non", en: "No" },
];

const isMarket = (s: string): s is Market => (MARKETS as readonly string[]).includes(s);

export const toggleMarket = (markets: Market[], m: Market): Market[] =>
  markets.includes(m) ? markets.filter((x) => x !== m) : [...markets, m];

export const esgMarketPrefs = ({ esg, markets }: EsgMarketChoice): string[] => [
  ...(esg ? [ESG_PREF] : []),
  ...MARKETS.filter((m) => markets.includes(m)).map((m) => MARKET + m),
];

export function splitEsgMarket(prefs: string[] = []): EsgMarketChoice & { others: string[] } {
  let esg = false;
  const markets: Market[] = [], others: string[] = [];
  for (const p of prefs) {
    const market = p.startsWith(MARKET) ? p.slice(MARKET.length) : "";
    if (p.trim().toUpperCase() === ESG_PREF) esg = true;
    else if (isMarket(market)) { if (!markets.includes(market)) markets.push(market); }
    else others.push(p);
  }
  return { esg, markets, others };
}
