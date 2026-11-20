import { inLang } from "../lib/format";
import { getAccessToken, signOut } from "./auth";
import { DEMO, demoRequest } from "./demo";
import { ApiError } from "./errors";
import type { ErrorCode } from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const PREFIX = "/v1";

let onSessionLost: () => void = () => {};
export const setSessionLostHandler = (fn: () => void) => { onSessionLost = fn; };

type Opts = { method?: string; query?: Record<string, string | number | undefined | null>; body?: unknown; signal?: AbortSignal };

const STATUS_CODE: Record<number, ErrorCode> = { 400: "VALIDATION_ERROR", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 504: "AGENT_TIMEOUT" };

async function send(path: string, o: Opts, token: string): Promise<Response> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(o.query ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const s = qs.toString();
  const url = `${BASE}${PREFIX}${path}${s ? `?${s}` : ""}`;
  try {
    return await fetch(url, {
      method: o.method ?? "GET",
      headers: { Authorization: `Bearer ${token}`, ...(o.body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: o.body !== undefined ? JSON.stringify(o.body) : undefined,
      signal: o.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("NETWORK", "", 0);
  }
}

export async function request<T>(path: string, o: Opts = {}): Promise<T> {
  if (DEMO) {
    try { return (await demoRequest(path, o, await getAccessToken())) as T; } catch (e) {
      if (e instanceof ApiError && e.code === "UNAUTHORIZED") throw sessionLost();
      throw e;
    }
  }
  let res = await send(path, o, await getAccessToken());
  if (res.status === 401) res = await send(path, o, await getAccessToken(true).catch(() => { throw sessionLost(); }));
  if (res.status === 401) throw sessionLost();
  if (res.status === 204) return undefined as T;
  const json = await res.json().catch(() => null);
  if (!res.ok) {
    const err = json?.error;
    throw new ApiError((err?.code as ErrorCode) ?? STATUS_CODE[res.status] ?? "INTERNAL", err?.message ?? "", res.status, err?.requestId);
  }
  return json as T;
}

function sessionLost() {
  signOut();
  onSessionLost();
  return new ApiError("UNAUTHORIZED", inLang("Session expirée.", "Session expired."), 401);
}
