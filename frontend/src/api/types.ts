export type Currency = "CAD" | "USD";
export type RiskLevel = "low" | "low_moderate" | "moderate" | "high";

export type ErrorCode =
  | "UNAUTHORIZED" | "FORBIDDEN" | "VALIDATION_ERROR" | "CONVERSATION_NOT_FOUND"
  | "PORTFOLIO_NOT_FOUND" | "ASSET_NOT_FOUND" | "MANDATE_NOT_FOUND" | "RUN_NOT_FOUND"
  | "MANDATE_NOT_CONFIRMED" | "GUARDRAIL_BLOCKED" | "AGENT_TIMEOUT" | "INTERNAL"
  | "NETWORK";

export type Jurisdiction =
  | "CA" | "QC" | "ON" | "BC" | "AB" | "SK" | "MB" | "NB" | "NS" | "PE" | "NL" | "YT" | "NT" | "NU";

export type InvestorProfile = {
  riskLevel?: RiskLevel;
  riskTolerance?: number;
  riskCapacity?: number;
  province?: Jurisdiction;
  horizonMinYears: number;
  horizonMaxYears?: number | null;
  objective: string;
  constraints?: string[];
  preferences?: string[];
  excludedAssetClasses?: string[];
};

export type User = {
  userId: string;
  username: string;
  displayName?: string;
  baseCurrency?: Currency;
  investorProfile: InvestorProfile | null;
};

export type Conversation = {
  sessionId: string;
  title?: string;
  userLanguage?: string;
  createdAt: string;
  updatedAt: string;
};
export type Page<T> = { items: T[]; nextCursor?: string | null };

export type ExplanationSource = { id: string; dataset?: string; asOf?: string; note?: string };
export type ExplanationStep = {
  agentId: string; tool: string; params?: Record<string, unknown>;
  status: "ok" | "error" | "empty"; durationMs?: number;
};
export type ExplanationCheck = {
  agentId: string; rule: string; status: "pass" | "warn" | "fail" | "not_verified"; message: string;
  reasonCode?: string;
  scenario?: number;
};
export type Explanation = {
  sources: ExplanationSource[];
  assumptions?: string[];
  limitations?: string[];
  steps: ExplanationStep[];
  checks?: ExplanationCheck[];
};

export type Message = {
  messageId: string;
  sessionId: string;
  role: "user" | "assistant";
  content: string;
  status: "done" | "pending" | "error";
  createdAt: string;
  explanation?: Explanation;
  quickReplies?: string[];
  mandateDraft?: MandateCreateRequest;
  runId?: string;
};
export type SpeechSession = { url: string; languageCode: "fr-CA" | "en-US"; sampleRate: number; expiresIn: number };

export type MessageCreateResponse = { userMessage: Message; assistantMessage: Message };

export type Holding = { ticker: string; quantity: number; avgCost: number };
export type Portfolio = { portfolioId: string; name: string; baseCurrency: Currency; holdings: Holding[]; updatedAt: string };

export type SummaryRange = "1m" | "6m" | "1y" | "5y";
export type Slice = { label: string; weight: number };
export type SummaryHolding = {
  ticker: string; name: string; assetClass: string; quantity: number; avgCost: number; currency: string;
  price: number; value: number; weight: number; pnl: number; pnlPct: number; dayChangePct: number;
  sector?: string; stale?: boolean;
};
export type PortfolioSummary = {
  portfolioId: string;
  baseCurrency: Currency;
  asOf: string;
  totals: { value: number; cost: number; pnl: number; pnlPct: number; dayChange: number; dayChangePct: number };
  holdings: SummaryHolding[];
  allocation: { byAssetClass: Slice[]; bySector: Slice[]; byCurrency: Slice[] };
  performance: { range: SummaryRange; points: { date: string; value: number }[] };
  risk: { volatility: number; maxDrawdown: number };
  warnings?: string[];
  explanation?: Explanation;
};

export type Asset = { ticker: string; name: string; assetClass: string; market?: string; currency?: string; sector?: string };

export type AssetDetail = {
  ticker: string; name: string; assetClass: string; market?: string | null; currency?: string | null;
  sector?: string | null; industry?: string | null; country?: string | null;
  description?: string; website?: string;
  asOf: string; price: number; dayChangePct: number | null;
  range: SummaryRange; rangeChangePct: number | null; points: { date: string; close: number }[];
  stats: { high52w: number | null; low52w: number | null; volatility: number | null; maxDrawdown: number | null; historyStart: string };
  source?: string;
};
export type AgentInfo = { id: string; name: string; role: string; allowedTools: string[]; delegatesTo?: string[]; limits?: Record<string, number> };
export type ModuleInfo = { id: string; name: string; role: string };
export type ToolInfo = { id: string; description: string; reads?: string[] };
export type AgentsRegistry = { agents: AgentInfo[]; modules?: ModuleInfo[]; tools: ToolInfo[] };

export type MandateMode = "add_asset" | "rebalance" | "diagnose" | "build";
export type MandateObjective = "growth" | "income" | "preservation" | "project" | "retirement";
export type MandateOperation = {
  action: "add" | "remove" | "set_weight";
  ticker: string;
  amount?: number;
  weight?: number;
  currency?: Currency;
};

export type MandateCreateRequest = {
  portfolioId: string;
  mode: MandateMode;
  objective: MandateObjective;
  objectiveDetail?: string;
  horizonYears: number;
  riskTolerance: number;
  riskCapacity: number;
  maxAcceptableLossPct?: number;
  constraints?: string[];
  preferences?: {
    esg?: boolean;
    excludedSectors?: string[];
    excludedAssetClasses?: string[];
    excludedIndustries?: string[];
    preferredIndustries?: { industry: string; minWeight?: number | null }[];
  };
  province: Jurisdiction;
  userLanguage: string;
  operations?: MandateOperation[];
  subjectTicker?: string;
  buildAmount?: number;
  compareCategory?: "short-term-bonds" | "aggregate-bonds" | "balanced-allocation" | "canadian-equity" | "us-equity" | "global-equity";
  fieldSources?: Record<string, "persona" | "user_answer" | "team_assumption" | "slider">;
};

export type MandateWarning = { code: string; message: string; params?: Record<string, string | number> };

export type Mandate = {
  sessionId: string;
  version: number;
  mandate: MandateCreateRequest;
  riskProfile: number;
  effectiveMaxLossPct: number;
  warnings?: (MandateWarning | string)[];
  changedFields?: string[];
  confirmedAt: string;
};

export type Evidence = {
  id: string;
  kind: "metric" | "etf_fact" | "regulation" | "assumption";
  label: string;
  value?: number;
  formatted?: string;
  scenario?: number;
  method?: string;
  window?: string;
  currency?: string;
  source: string;
  asOf?: string;
  document?: string;
  section?: string;
  excerpt?: string;
  jurisdiction?: string;
  url?: string;
  caveats?: string[];
  documentType?: "regulation" | "companion_policy" | "staff_notice" | "guidance_note" | "bulletin" | "rule" | "web_page" | "proposed_regulation_notice" | "disclosure_document";
  regulator?: string;
  status?: "en_vigueur" | "projet";
  sectionTitle?: string;
  language?: string;
};

export type BuiltHolding = {
  symbol: string;
  name: string;
  industry: string;
  weight: number;
  evidence: { weight: string; beta: string; expectedReturn: string };
  quantity?: number;
  price?: number;
  currency?: string;
};
export type BuildParameter = { key: string; value: number | string[] | { industry: string; minWeight?: number | null }[]; riskProfile?: number; evidence?: string; currency?: string; origin?: "user" | "portfolio" | "default" };

export type Scenario = {
  index: 0 | 1 | 2;
  label: string;
  description?: string;
  proxyNote?: string;
  allocation?: Slice[];
  holdings?: BuiltHolding[];
  parameters?: BuildParameter[];
  metrics?: Record<string, string>;
  verdict?: "pass" | "warn" | "fail";
};

export type RuleVerdict = {
  rule: string;
  scenario?: number;
  status: "pass" | "warn" | "fail" | "not_verified";
  reasonCode: string;
  evidence?: string[];
  citations?: string[];
  threshold?: { value: number; nature: "text" | "team_assumption" };
  messageEn?: string;
  message?: string;
};

export type NoticeCitations = { R5?: string[]; R9?: string[] };

export type NarrativeSectionKey = "data_used" | "why" | "limits" | "what_would_change";
export type NarrativeSection = { key: NarrativeSectionKey; textEn: string; text: string };
export type Narrative = {
  sections: NarrativeSection[];
  language: string;
  hiddenSentences?: { section: string; reason: string }[];
};

export type VerifierReport = {
  placeholdersResolved: number;
  placeholdersTotal: number;
  handwrittenNumbers: number;
  forbiddenPhrases: number;
  placeholdersMatch: boolean;
};

export type RunStatus = "partial" | "done" | "error";
export type Run = {
  runId: string;
  sessionId: string;
  mandateVersion: number;
  status: RunStatus;
  rulesVersion?: number;
  datasetVersion: string;
  userLanguage: string;
  scenarios: Scenario[];
  verdicts: RuleVerdict[];
  evidence: Evidence[];
  noticeCitations?: NoticeCitations;
  narrative?: Narrative;
  verifier?: VerifierReport;
  jurisdictionNotices?: string[];
  explanation?: Explanation;
  createdAt: string;
  completedAt?: string;
};

export type RunCreateRequest = { mandateVersion: number };
