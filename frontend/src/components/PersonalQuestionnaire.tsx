import { useState, type FormEvent } from "react";
import { isComplete, QUESTIONS, qLabel, qOptions } from "../lib/risk";
import { useT } from "../lib/i18n";
type Answers = Record<string, number>;
export default function PersonalQuestionnaire({
  initial = {}, submitLabel, onSubmit,
}: { initial?: Answers; submitLabel: string; onSubmit: (a: Answers) => void }) {
  const { lang, L } = useT();
  const [a, setA] = useState<Answers>(initial);
  const [tried, setTried] = useState(false);
  const done = QUESTIONS.filter((q) => a[q.id] !== undefined).length;
  function submit(e: FormEvent) {
    e.preventDefault();
    setTried(true);
    if (isComplete(a)) onSubmit(a);
  }
  return (
    <form onSubmit={submit} className="questionnaire" noValidate>
      <div className="q-progress" aria-live="polite">
        <div className="alloc-bar" style={{ margin: 0, flex: 1, height: 6 }}><span style={{ width: `${(done / QUESTIONS.length) * 100}%`, background: "var(--red)" }} /></div>
        <span className="muted small">{done} / {QUESTIONS.length}</span>
      </div>
      {QUESTIONS.map((q, i) => (
        <fieldset key={q.id} className={`q${tried && a[q.id] === undefined ? " missing" : ""}`}>
          <legend>{i + 1}. {qLabel(q, lang)}</legend>
          <div className="opts">
            {qOptions(q, lang).map((o, j) => (
              <label key={o} className={`opt${a[q.id] === j ? " on" : ""}`}>
                <input type="radio" name={`perso-${q.id}`} checked={a[q.id] === j} onChange={() => setA({ ...a, [q.id]: j })} />
                {o}
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      {tried && !isComplete(a) && <p className="error" role="alert">{L("Veuillez répondre à toutes les questions.", "Please answer every question.")}</p>}
      <div><button type="submit" className="btn">{submitLabel}</button></div>
    </form>
  );
}
