import { inLang } from "../lib/format";
import type { ErrorCode } from "./types";

export class ApiError extends Error {
  constructor(public code: ErrorCode, message: string, public status: number, public requestId?: string) {
    super(message);
  }
}

const LABELS: Partial<Record<ErrorCode, string>> = {
  UNAUTHORIZED: "Votre session a expiré. Reconnectez-vous.",
  FORBIDDEN: "Accès refusé.",
  CONVERSATION_NOT_FOUND: "Conversation introuvable.",
  PORTFOLIO_NOT_FOUND: "Portefeuille introuvable.",
  ASSET_NOT_FOUND: "Un des tickers n'existe pas dans l'univers d'actifs.",
  MANDATE_NOT_FOUND: "Mandat introuvable.",
  RUN_NOT_FOUND: "Analyse introuvable.",
  MANDATE_NOT_CONFIRMED: "Le mandat doit d'abord être confirmé avant de lancer l'analyse.",
  GUARDRAIL_BLOCKED: "Cette demande ne peut pas être traitée (simulation seulement : aucune transaction, aucune promesse de rendement, aucun conseil personnalisé).",
  AGENT_TIMEOUT: "Les agents ont mis trop de temps à répondre. Réessayez.",
  NETWORK: "Le serveur est injoignable. Vérifiez votre connexion.",
};

const LABELS_EN: Partial<Record<ErrorCode, string>> = {
  UNAUTHORIZED: "Your session has expired. Please sign in again.",
  FORBIDDEN: "Access denied.",
  CONVERSATION_NOT_FOUND: "Conversation not found.",
  PORTFOLIO_NOT_FOUND: "Portfolio not found.",
  ASSET_NOT_FOUND: "One of the tickers does not exist in the asset universe.",
  MANDATE_NOT_FOUND: "Mandate not found.",
  RUN_NOT_FOUND: "Analysis not found.",
  MANDATE_NOT_CONFIRMED: "The mandate must be confirmed before the analysis can start.",
  GUARDRAIL_BLOCKED: "This request cannot be processed (simulation only: no transactions, no promised returns, no personalised advice).",
  AGENT_TIMEOUT: "The agents took too long to answer. Try again.",
  NETWORK: "The server is unreachable. Check your connection.",
};

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const labels = inLang("fr", "en") === "en" ? LABELS_EN : LABELS;
    const base = e.message || labels[e.code] || inLang("Une erreur est survenue.", "Something went wrong.");
    return e.requestId && e.code !== "GUARDRAIL_BLOCKED" ? `${base} (${inLang("réf.", "ref.")} ${e.requestId})` : base;
  }
  return inLang("Une erreur est survenue.", "Something went wrong.");
}
