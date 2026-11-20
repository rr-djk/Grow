export const ASSET_CLASSES: { code: string; fr: string; en: string }[] = [
  { code: "equity", fr: "Actions", en: "Stocks" },
  { code: "etf_equity", fr: "FNB d'actions", en: "Equity ETFs" },
  { code: "etf_bond", fr: "FNB d'obligations", en: "Bond ETFs" },
  { code: "etf_commodity", fr: "FNB de matières premières", en: "Commodity ETFs" },
  { code: "etf_reit", fr: "FNB immobiliers", en: "Real-estate ETFs" },
  { code: "crypto", fr: "Crypto-actifs", en: "Crypto assets" },
];
const OTHER: Record<string, { fr: string; en: string }> = {
  etf: { fr: "FNB", en: "ETF" },
  index: { fr: "Indice", en: "Index" },
  bond: { fr: "Obligations", en: "Bonds" },
  cash: { fr: "Encaisse", en: "Cash" },
};

export const SEARCH_CLASSES: { code: string; fr: string; en: string }[] = [
  { code: "equity", fr: "Action", en: "Stock" },
  { code: "etf", fr: "FNB", en: "ETF" },
  { code: "crypto", fr: "Crypto", en: "Crypto" },
];

export const assetClassName = (code: string, lang: "fr" | "en") => {
  const c = ASSET_CLASSES.find((a) => a.code === code) ?? OTHER[code];
  return c ? c[lang] : code;
};
