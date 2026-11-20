const NBSP = "\u00a0";
type L = "fr" | "en";
let current: L = "fr";
export function setFormatLang(l: L) { current = l; }
const MONTHS: Record<L, string[]> = {
  fr: ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};
const months = () => MONTHS[current];
const decSep = () => (current === "en" ? "." : ",");
const pctUnit = () => (current === "en" ? "%" : NBSP + "%");

export function money(n: number, decimals = 2) {
  const [int, dec] = Math.abs(n).toFixed(decimals).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, current === "en" ? "," : NBSP);
  return (n < 0 ? "−" : "") + grouped + (dec ? decSep() + dec : "");
}

export function cad(n: number, decimals = 2) {
  return current === "en" ? (n < 0 ? "−" : "") + "$" + money(Math.abs(n), decimals) : money(n, decimals) + NBSP + "$";
}

export function pct(n: number) {
  return (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(2).replace(".", decSep()) + pctUnit();
}

export function signedCad(n: number) {
  return (n >= 0 ? "+" : "−") + cad(Math.abs(n));
}

export function shortDate(ts: number, withYear = false) {
  const d = new Date(ts * 1000);
  if (withYear) return `${months()[d.getMonth()]} ${d.getFullYear()}`;
  return current === "en" ? `${months()[d.getMonth()]} ${d.getDate()}` : `${d.getDate()} ${months()[d.getMonth()]}`;
}

export function fullDate(ts: number) {
  const d = new Date(ts * 1000);
  return current === "en" ? `${months()[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}` : `${d.getDate()} ${months()[d.getMonth()]} ${d.getFullYear()}`;
}

export function clock(ts: number) {
  return time(new Date(ts * 1000));
}

export function fullDateTime(ts: number) {
  return `${fullDate(ts)}, ${clock(ts)}`;
}

export function compact(n: number) {
  const a = Math.abs(n);
  const [v, s] = a >= 1e12 ? [n / 1e12, "T"] : a >= 1e9 ? [n / 1e9, "G"] : a >= 1e6 ? [n / 1e6, "M"] : a >= 1e3 ? [n / 1e3, "k"] : [n, ""];
  return money(v, s ? 2 : 0) + (s ? NBSP + s : "");
}

export function time(d: Date) {
  return `${d.getHours()} h ${String(d.getMinutes()).padStart(2, "0")}`;
}

export function amount(n: number, currency: string, decimals = 2) {
  return money(n, decimals) + NBSP + currency;
}

export function signedAmount(n: number, currency: string) {
  return (n >= 0 ? "+" : "−") + amount(Math.abs(n), currency);
}

export function plainPct(n: number, decimals = 1) {
  return money(n, decimals) + pctUnit();
}

export function toSeconds(iso: string) {
  return Math.floor(new Date(iso.length === 10 ? `${iso}T12:00:00Z` : iso).getTime() / 1000);
}

export function dateTimeFr(iso: string) {
  return new Date(iso).toLocaleDateString(current === "en" ? "en-CA" : "fr-CA", { day: "numeric", month: "short" });
}

export function localeDateTime(iso: string) {
  return new Date(iso).toLocaleString(current === "en" ? "en-CA" : "fr-CA");
}

export function todayLong() {
  return new Date().toLocaleDateString(current === "en" ? "en-CA" : "fr-CA", { weekday: "short", day: "numeric", month: "long", year: "numeric" });
}

export function inLang(fr: string, en: string) {
  return current === "en" ? en : fr;
}

export function colon() {
  return current === "en" ? ":" : " :";
}
