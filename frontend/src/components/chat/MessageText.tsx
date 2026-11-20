import { useId, useState, type ReactNode } from "react";
import type { Evidence } from "../../api/types";
import type { Lang } from "../../lib/i18n";
import EvidenceText from "./EvidenceText";
import { MoreToggle } from "./RuleItem";

type ListBlock = { kind: "ul" | "ol"; items: string[] };
export type Block = { kind: "p" | "h" | "quote"; text: string } | ListBlock;

const isList = (b: Block): b is ListBlock => b.kind === "ul" || b.kind === "ol";

const LIST_ITEM = /^(?:[-*•–]|\d{1,2}[.)])\s+/;
const HEADING = /^#{1,6}\s+/;
const QUOTE_LINE = /^>\s?/;
const RULE_START = /^(?:\*\*)?(?:[Rr][èeé]gle\s+|[Rr]ule\s+)?R(?:10|[1-9])(?!\d)\s*(?:\([^)\n]{0,60}\)\s*)?(?:\*\*)?\s*(?:\([^)\n]{0,60}\)\s*)?(?::|[–—-]\s)/;
const PLACEHOLDER_ONLY = /^\{(?:EV|KB)-\d+\}$/;

const SHOW_ALL = 160;
const HEAD_MAX = 110;

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const chunk of text.replace(/\r\n?/g, "\n").split(/\n[ \t]*\n/)) {
    let para: string[] = [];
    let list: ListBlock | null = null;
    const endPara = () => { if (para.length) blocks.push(paragraph(para)); para = []; };
    const endList = () => { if (list) blocks.push(list); list = null; };
    for (const raw of chunk.split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      const item = LIST_ITEM.exec(line);
      if (item) {
        const kind = /^\d/.test(line) ? "ol" : "ul";
        endPara();
        if (list && list.kind !== kind) endList();
        list ??= { kind, items: [] };
        list.items.push(line.slice(item[0].length));
      } else if (HEADING.test(line)) {
        endPara(); endList();
        blocks.push({ kind: "h", text: line.replace(HEADING, "") });
      } else if (list && /^\s/.test(raw)) {
        list.items[list.items.length - 1] += `\n${line}`;
      } else {
        endList();
        para.push(line);
      }
    }
    endPara(); endList();
  }
  return blocks;
}

function paragraph(lines: string[]): Block {
  if (lines.every((l) => QUOTE_LINE.test(l))) return { kind: "quote", text: lines.map((l) => l.replace(QUOTE_LINE, "")).join("\n") };
  const text = lines.join("\n");
  if (/^[«“"]/.test(text) && /[»”"][.,;]?$/.test(text)) return { kind: "quote", text };
  return { kind: "p", text };
}

type Span = { kind: "text" | "strong" | "code"; text: string; start: number; end: number };
const INLINE = /\*\*(\S(?:[\s\S]*?\S)?)\*\*|`([^`\n]+)`/g;

export function spans(text: string): Span[] {
  const out: Span[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    const i = m.index ?? 0;
    if (i > last) out.push({ kind: "text", text: text.slice(last, i), start: last, end: i });
    const end = i + m[0].length;
    out.push(m[1] !== undefined ? { kind: "strong", text: m[1], start: i, end } : { kind: "code", text: m[2], start: i, end });
    last = end;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last), start: last, end: text.length });
  return out;
}

const visibleLength = (s: string) => s.replace(/\*\*|`/g, "").length;

export function ruleCut(text: string): { at: number; ellipsis: boolean } | null {
  if (visibleLength(text) <= SHOW_ALL) return null;
  const segments = spans(text);
  const styled = segments.filter((s) => s.kind !== "text");
  const inside = (pos: number) => styled.some((s) => s.start < pos && pos < s.end);
  const fits = (pos: number) => visibleLength(text.slice(0, pos)) <= HEAD_MAX;
  const hasRest = (pos: number) => text.slice(pos).trim().length > 0;

  const newline = text.indexOf("\n");
  if (newline > 0 && fits(newline) && !inside(newline)) return { at: newline, ellipsis: false };

  for (const m of text.matchAll(/[.!?…](?:\*\*)?(?=\s+[A-ZÀ-ÖØ-Þ«"“({[])/g)) {
    const at = (m.index ?? 0) + m[0].length;
    if (!fits(at)) break;
    if (!inside(at) && hasRest(at)) return { at, ellipsis: false };
  }
  for (let at = text.length; at > HEAD_MAX / 2; at--) {
    if (/\s/.test(text[at]) && fits(at) && !inside(at) && hasRest(at)) return { at, ellipsis: true };
  }
  return null;
}

function emphasizeRule(text: string): string {
  return text.startsWith("**") ? text : text.replace(/^((?:[Rr][èeé]gle\s+|[Rr]ule\s+)?R(?:10|[1-9]))(?=\s*[:(–—-])/, "**$1**");
}

function Inline({ text, evidence, lang, resolve }: { text: string; evidence: Evidence[]; lang: Lang; resolve: boolean }) {
  const body = (s: string) => (resolve ? <EvidenceText text={s} evidence={evidence} lang={lang} /> : s);
  return (
    <>
      {spans(text).map((s, i) => {
        if (s.kind === "strong") return <strong key={i}>{body(s.text)}</strong>;
        if (s.kind === "code" && !PLACEHOLDER_ONLY.test(s.text)) return <code key={i}>{s.text}</code>;
        return <span key={i}>{body(s.text)}</span>;
      })}
    </>
  );
}

function RuleText({ text, render, lang }: { text: string; render: (s: string) => ReactNode; lang: Lang }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const cut = ruleCut(text);
  if (!cut) return <>{render(text)}</>;
  return (
    <>
      <span id={id}>
        {open ? render(text) : <>{render(text.slice(0, cut.at).trimEnd())}{cut.ellipsis ? "…" : ""}</>}
      </span>{" "}
      <MoreToggle open={open} onToggle={() => setOpen((o) => !o)} controls={id} lang={lang} />
    </>
  );
}

export default function MessageText({ text, evidence, lang, resolve }: {
  text: string;
  evidence: Evidence[];
  lang: Lang;
  resolve: boolean;
}) {
  const render = (s: string) => <Inline text={s} evidence={evidence} lang={lang} resolve={resolve} />;
  const content = (s: string) => (RULE_START.test(s) ? <RuleText text={emphasizeRule(s)} render={render} lang={lang} /> : render(s));
  const ruleClass = (s: string) => (RULE_START.test(s) ? "msg-rule" : undefined);
  return (
    <div className="msg-text">
      {parseBlocks(text).map((b, i) => {
        if (isList(b)) {
          const List = b.kind;
          return <List key={i}>{b.items.map((it, j) => <li key={j} className={ruleClass(it)}>{content(it)}</li>)}</List>;
        }
        if (b.kind === "quote") return <blockquote key={i} className="msg-quote">{render(b.text)}</blockquote>;
        if (b.kind === "h") return <p key={i} className="msg-h">{render(b.text)}</p>;
        return <p key={i} className={ruleClass(b.text)}>{content(b.text)}</p>;
      })}
    </div>
  );
}
