import { isComplete } from "./risk";
type Answers = Record<string, number>;
const KEY = "af.personal.answers";
export function loadPersonalAnswers(): Answers | null {
  try {
    const v = JSON.parse(sessionStorage.getItem(KEY) ?? "null");
    return v && typeof v === "object" && isComplete(v) ? v : null;
  } catch { return null; }
}
export function savePersonalAnswers(a: Answers) {
  try { sessionStorage.setItem(KEY, JSON.stringify(a)); } catch {  }
}
